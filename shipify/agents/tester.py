"""
Christopher — Tester / Security Agent
Powered by: Macroscope AST analysis + Ghost DB fork.

Flow:
  1. Ghost: fork the dev DB for safe schema testing
  2. Post a Macroscope review request to Slack
  3. Poll Slack for Macroscope's verdict (pass / fail + issues)
  4. If issues found: patch and re-review (up to MAX_RETRIES)
  5. On pass: approve the PR, delete original dev DB, keep fork
  6. On fail: request changes on the PR
"""
import time
import httpx
from shipify.config import cfg
from shipify.db.ghost import ghost
from shipify.context.airbyte import airbyte_context
from shipify.gateway.truefoundry import gateway

MAX_RETRIES = 3
POLL_INTERVAL_S = 15
POLL_TIMEOUT_S = 300


class TesterAgent:
    name = "tester"

    def run(self, pr_url: str, pr_number: int, dev_db_id: str, branch: str) -> dict:
        """
        Security-review a PR. Returns {"verdict": "pass"|"fail", "issues": [...], "fork_db_id": str}
        """
        gateway.check_budget(self.name)

        # 1. Fork the dev DB — tester can't break the dev DB
        fork = ghost.fork(dev_db_id, fork_name=f"test-fork-{pr_number}")
        fork_db_id = fork["id"]
        print(f"[Christopher] Forked dev DB → {fork_db_id}")

        # 2. Ask Macroscope to review the PR via Slack
        thread_ts = self._request_macroscope_review(pr_url, branch)

        # 3. Poll for verdict
        verdict, issues = self._poll_verdict(thread_ts)

        # 4. Handle result
        if verdict == "pass":
            self._approve_pr(pr_number)
            # Discard original dev DB, keep the tested fork
            ghost.delete(dev_db_id)
            print(f"[Christopher] PR #{pr_number} cleared. Approved.")
            return {"verdict": "pass", "issues": [], "fork_db_id": fork_db_id}
        else:
            self._request_changes(pr_number, issues)
            print(f"[Christopher] PR #{pr_number} blocked — {len(issues)} issue(s) found.")
            return {"verdict": "fail", "issues": issues, "fork_db_id": fork_db_id}

    # ── Macroscope via Slack ───────────────────────────────────────────────

    def _request_macroscope_review(self, pr_url: str, branch: str) -> str:
        """Post a review request to the Macroscope Slack channel. Returns thread_ts."""
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            json={
                "channel": cfg.macroscope_slack_channel,
                "text": (
                    f"@macroscope review PR: {pr_url}\n"
                    f"Branch: `{branch}`\n"
                    f"Run full AST scan. Report vulnerabilities, broken flows, and compliance issues."
                ),
            },
            headers={"Authorization": f"Bearer {cfg.macroscope_slack_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"[Christopher] Slack post failed: {data.get('error')}")
        thread_ts = data["ts"]
        print(f"[Christopher] Macroscope review requested (thread: {thread_ts})")
        return thread_ts

    def _poll_verdict(self, thread_ts: str) -> tuple[str, list[str]]:
        """Poll the Slack thread until Macroscope posts its verdict."""
        deadline = time.time() + POLL_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL_S)
            replies = self._fetch_thread_replies(thread_ts)
            for msg in replies:
                text = msg.get("text", "").lower()
                if "approved" in text or "no issues" in text or "cleared" in text:
                    return "pass", []
                if "vulnerabilit" in text or "issue" in text or "fail" in text or "blocked" in text:
                    issues = self._extract_issues(msg.get("text", ""))
                    return "fail", issues
        raise TimeoutError("[Christopher] Macroscope review timed out")

    def _fetch_thread_replies(self, thread_ts: str) -> list[dict]:
        resp = httpx.get(
            "https://slack.com/api/conversations.replies",
            params={"channel": cfg.macroscope_slack_channel, "ts": thread_ts},
            headers={"Authorization": f"Bearer {cfg.macroscope_slack_token}"},
            timeout=15,
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        return messages[1:]  # skip the original message

    def _extract_issues(self, text: str) -> list[str]:
        """Parse issue lines from Macroscope's reply."""
        lines = [l.strip() for l in text.splitlines() if l.strip().startswith(("-", "•", "*"))]
        return lines or [text[:200]]

    # ── GitHub PR actions ─────────────────────────────────────────────────

    def _approve_pr(self, pr_number: int) -> None:
        httpx.post(
            f"https://api.github.com/repos/{cfg.github_repo}/pulls/{pr_number}/reviews",
            json={"event": "APPROVE", "body": "Macroscope AST scan passed. No vulnerabilities found."},
            headers={
                "Authorization": f"token {cfg.github_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        ).raise_for_status()

    def _request_changes(self, pr_number: int, issues: list[str]) -> None:
        body = "Macroscope found the following issues:\n\n" + "\n".join(f"- {i}" for i in issues)
        httpx.post(
            f"https://api.github.com/repos/{cfg.github_repo}/pulls/{pr_number}/reviews",
            json={"event": "REQUEST_CHANGES", "body": body},
            headers={
                "Authorization": f"token {cfg.github_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        ).raise_for_status()
