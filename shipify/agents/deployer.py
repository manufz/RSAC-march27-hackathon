"""
Amy — Deployment Agent
Powered by: TrueFoundry (deploy + observability) + Ghost DB promotion.

Flow:
  1. Ghost: promote the tested fork DB to production
  2. TrueFoundry: trigger deployment of the approved branch
  3. Poll health checks until live or timeout
  4. On failure: ghost_pause (instant rollback) + TrueFoundry rollback
  5. Log audit trail via ghost_logs
"""
import time
import httpx
from shipify.config import cfg
from shipify.db.ghost import ghost
from shipify.gateway.truefoundry import gateway

HEALTH_POLL_INTERVAL_S = 10
HEALTH_TIMEOUT_S = 300


class DeployerAgent:
    name = "deployer"

    def run(self, branch: str, pr_number: int, fork_db_id: str, version: str) -> dict:
        """
        Deploy an approved PR to production.
        Returns {"status": "live"|"rolled_back", "version": str, "prod_db_id": str}
        """
        gateway.check_budget(self.name)

        # 1. Promote the tested fork DB to production
        prod_db = ghost.promote(fork_db_id)
        prod_db_id = prod_db.get("id", fork_db_id)
        print(f"[Amy] Prod DB promoted: {prod_db_id}")

        # 2. Trigger TrueFoundry deployment
        deploy_id = self._trigger_deploy(branch, version)
        print(f"[Amy] Deployment triggered: {deploy_id}")

        # 3. Poll health checks
        healthy = self._wait_for_health(deploy_id)

        if healthy:
            self._merge_pr(pr_number)
            logs = ghost.logs(prod_db_id, limit=50)
            print(f"[Amy] v{version} is live. Audit log: {len(logs)} entries.")
            return {"status": "live", "version": version, "prod_db_id": prod_db_id}
        else:
            # Rollback: pause prod DB + TrueFoundry rollback
            ghost.pause(prod_db_id)
            self._rollback_deploy(deploy_id)
            print(f"[Amy] Rollback complete. v{version} did not go live.")
            return {"status": "rolled_back", "version": version, "prod_db_id": prod_db_id}

    # ── TrueFoundry API ───────────────────────────────────────────────────

    def _trigger_deploy(self, branch: str, version: str) -> str:
        resp = httpx.post(
            f"https://api.truefoundry.com/api/svc/v1/deployments",
            json={
                "workspaceFqn": cfg.truefoundry_workspace_fqn,
                "branch": branch,
                "version": version,
                "strategy": "rolling",
            },
            headers={
                "Authorization": f"Bearer {cfg.truefoundry_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["deploymentId"]

    def _wait_for_health(self, deploy_id: str) -> bool:
        """Poll TrueFoundry until deployment is healthy or times out."""
        deadline = time.time() + HEALTH_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(HEALTH_POLL_INTERVAL_S)
            status = self._get_deploy_status(deploy_id)
            print(f"[Amy] Health check: {status}")
            if status == "healthy":
                return True
            if status in ("failed", "error"):
                return False
        return False

    def _get_deploy_status(self, deploy_id: str) -> str:
        resp = httpx.get(
            f"https://api.truefoundry.com/api/svc/v1/deployments/{deploy_id}",
            headers={"Authorization": f"Bearer {cfg.truefoundry_api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("status", "unknown")

    def _rollback_deploy(self, deploy_id: str) -> None:
        httpx.post(
            f"https://api.truefoundry.com/api/svc/v1/deployments/{deploy_id}/rollback",
            headers={"Authorization": f"Bearer {cfg.truefoundry_api_key}"},
            timeout=30,
        ).raise_for_status()
        print(f"[Amy] TrueFoundry rollback triggered for {deploy_id}")

    # ── GitHub ────────────────────────────────────────────────────────────

    def _merge_pr(self, pr_number: int) -> None:
        httpx.put(
            f"https://api.github.com/repos/{cfg.github_repo}/pulls/{pr_number}/merge",
            json={"merge_method": "squash"},
            headers={
                "Authorization": f"token {cfg.github_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        ).raise_for_status()
        print(f"[Amy] PR #{pr_number} merged.")
