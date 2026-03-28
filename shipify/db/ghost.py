"""
Ghost MCP — agent database layer.

Each agent gets its own DB lifecycle:
  Developer  → ghost_create  per task, discarded on merge
  Tester     → ghost_fork    of dev DB, safe isolation
  Deployer   → promotes fork to prod, ghost_pause for rollback
"""
import httpx
from typing import Optional
from shipify.config import cfg


class GhostClient:
    """Thin wrapper around the Ghost MCP HTTP API."""

    def __init__(self):
        self._base = cfg.ghost_mcp_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {cfg.ghost_mcp_token}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, body: dict) -> dict:
        resp = httpx.post(f"{self._base}{path}", json=body, headers=self._headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        resp = httpx.delete(f"{self._base}{path}", headers=self._headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def create(self, name: str) -> dict:
        """Spin up a fresh isolated Postgres DB. Called by developer agent per task."""
        result = self._post("/databases", {"name": name})
        print(f"[Ghost] Created DB: {name} → {result.get('connection_string', '')[:40]}...")
        return result

    def fork(self, source_db_id: str, fork_name: str) -> dict:
        """Fork an existing DB. Called by tester agent for safe schema testing."""
        result = self._post(f"/databases/{source_db_id}/fork", {"name": fork_name})
        print(f"[Ghost] Forked {source_db_id} → {fork_name}")
        return result

    def promote(self, db_id: str) -> dict:
        """Promote a tested fork to production. Called by deployer agent."""
        result = self._post(f"/databases/{db_id}/promote", {})
        print(f"[Ghost] Promoted DB {db_id} to production")
        return result

    def pause(self, db_id: str) -> dict:
        """Instant rollback mechanism — pause a DB without destroying it."""
        result = self._post(f"/databases/{db_id}/pause", {})
        print(f"[Ghost] Paused DB {db_id} (rollback ready)")
        return result

    def resume(self, db_id: str) -> dict:
        result = self._post(f"/databases/{db_id}/resume", {})
        print(f"[Ghost] Resumed DB {db_id}")
        return result

    def delete(self, db_id: str) -> dict:
        """Discard a DB — called after successful merge."""
        result = self._delete(f"/databases/{db_id}")
        print(f"[Ghost] Deleted DB {db_id}")
        return result

    def logs(self, db_id: str, limit: int = 100) -> list[dict]:
        """Fetch audit logs for a DB. Used by deployer for audit trail."""
        resp = httpx.get(
            f"{self._base}/databases/{db_id}/logs",
            headers=self._headers,
            params={"limit": limit},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("logs", [])

    def execute_sql(self, db_id: str, sql: str) -> dict:
        return self._post(f"/databases/{db_id}/query", {"sql": sql})

    def inspect_schema(self, db_id: str) -> dict:
        resp = httpx.get(
            f"{self._base}/databases/{db_id}/schema",
            headers=self._headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


ghost = GhostClient()
