"""
OpenClaw pipeline — orchestrates Sean → Christopher → Amy.

This is the agent loop. It:
  1. Syncs Airbyte context (Slack → vector store)
  2. Runs Sean (developer) to build + open a PR
  3. Runs Christopher (tester) to security-review the PR
  4. If Christopher passes: runs Amy (deployer) to ship it
  5. Prints a spend report from TrueFoundry at the end
"""
import uuid
import re
from shipify.agents.developer import DeveloperAgent
from shipify.agents.tester import TesterAgent
from shipify.agents.deployer import DeployerAgent
from shipify.context.airbyte import airbyte_context
from shipify.gateway.truefoundry import gateway


def run_pipeline(prompt: str, version: str = "0.0.1") -> dict:
    """
    Entry point for a full Shipify pipeline run.

    Args:
        prompt:  Natural-language feature description (e.g. "Add OAuth2 login")
        version: Semver string for the deployment (e.g. "1.4.2")

    Returns:
        Summary dict with PR URL, DB IDs, deploy status, and spend.
    """
    task_id = str(uuid.uuid4())[:8]
    branch = f"shipify/{task_id}"

    print(f"\n{'='*60}")
    print(f"  Shipify Pipeline — task {task_id}")
    print(f"  Prompt: {prompt[:80]}")
    print(f"{'='*60}\n")

    # ── 0. Sync shared context ─────────────────────────────────────────
    print("[Pipeline] Syncing Airbyte context...")
    try:
        airbyte_context.trigger_sync()
    except Exception as e:
        print(f"[Pipeline] Airbyte sync skipped (non-fatal): {e}")

    # ── 1. Sean: build + PR ────────────────────────────────────────────
    print("\n[Pipeline] → Sean: building...")
    sean_result = DeveloperAgent().run(prompt=prompt, task_id=task_id, branch=branch)
    pr_url = sean_result["pr_url"]
    dev_db_id = sean_result["db_id"]

    # Extract PR number from URL (e.g. https://github.com/org/repo/pull/48)
    pr_number = int(re.search(r"/pull/(\d+)", pr_url).group(1))

    # ── 2. Christopher: security review ───────────────────────────────
    print("\n[Pipeline] → Christopher: reviewing...")
    chris_result = TesterAgent().run(
        pr_url=pr_url,
        pr_number=pr_number,
        dev_db_id=dev_db_id,
        branch=branch,
    )

    if chris_result["verdict"] == "fail":
        print(f"\n[Pipeline] ✗ Blocked by Christopher. Issues:\n")
        for issue in chris_result["issues"]:
            print(f"  {issue}")
        return {
            "status": "blocked",
            "task_id": task_id,
            "pr_url": pr_url,
            "issues": chris_result["issues"],
            "spend": gateway.spend_report(),
        }

    fork_db_id = chris_result["fork_db_id"]

    # ── 3. Amy: deploy ─────────────────────────────────────────────────
    print("\n[Pipeline] → Amy: deploying...")
    amy_result = DeployerAgent().run(
        branch=branch,
        pr_number=pr_number,
        fork_db_id=fork_db_id,
        version=version,
    )

    spend = gateway.spend_report()
    total = sum(spend.values())

    print(f"\n{'='*60}")
    print(f"  Pipeline complete — {amy_result['status'].upper()}")
    print(f"  Version: v{version} | Task: {task_id}")
    print(f"  Spend: developer=${spend['developer']:.4f} | "
          f"tester=${spend['tester']:.4f} | "
          f"deployer=${spend['deployer']:.4f} | "
          f"total=${total:.4f}")
    print(f"{'='*60}\n")

    return {
        "status": amy_result["status"],
        "task_id": task_id,
        "version": version,
        "pr_url": pr_url,
        "prod_db_id": amy_result["prod_db_id"],
        "spend": spend,
    }
