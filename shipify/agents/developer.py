"""
Sean — Developer Agent
Powered by: Kiro CLI (spec → design → tasks → code) + Ghost DB per task.

Flow:
  1. Pull relevant context from Airbyte/Pinecone
  2. Write a Kiro spec file from the natural-language prompt
  3. Run `kiro spec` headlessly to generate design doc + task queue
  4. Run `kiro run` to execute tasks (hooks fire on every file save)
  5. Open a GitHub PR when done
  6. Ghost: create isolated DB at start, discard on merge
"""
import json
import subprocess
import textwrap
import httpx
from pathlib import Path

from shipify.config import cfg
from shipify.db.ghost import ghost
from shipify.context.airbyte import airbyte_context
from shipify.gateway.truefoundry import gateway


class DeveloperAgent:
    name = "developer"

    def run(self, prompt: str, task_id: str, branch: str) -> dict:
        """
        Execute a full development cycle for the given prompt.
        Returns {"pr_url": str, "db_id": str, "branch": str}
        """
        gateway.check_budget(self.name)

        # 1. Fetch shared context (Slack decisions, prior sprint notes)
        context_chunks = airbyte_context.query_context(prompt)
        context_text = "\n".join(c["text"] for c in context_chunks)

        # 2. Spin up an isolated Ghost DB for this task
        db = ghost.create(name=f"dev-{task_id}")
        db_id = db["id"]
        conn_str = db["connection_string"]
        print(f"[Sean] DB ready: {db_id}")

        # 3. Write the Kiro spec file
        spec_path = self._write_spec(prompt, context_text, conn_str, task_id)

        # 4. Run Kiro headlessly: spec → design → tasks
        self._kiro_spec(spec_path)

        # 5. Run Kiro tasks (hooks trigger on every file save)
        self._kiro_run(spec_path)

        # 6. Open a GitHub PR
        pr_url = self._open_pr(branch, task_id, prompt)

        print(f"[Sean] PR opened: {pr_url}")
        return {"pr_url": pr_url, "db_id": db_id, "branch": branch}

    # ── Kiro CLI helpers ───────────────────────────────────────────────────

    def _write_spec(self, prompt: str, context: str, conn_str: str, task_id: str) -> Path:
        workspace = Path(cfg.kiro_workspace) / task_id
        workspace.mkdir(parents=True, exist_ok=True)
        spec_path = workspace / "spec.md"
        spec_path.write_text(
            textwrap.dedent(f"""\
                # Shipify Task: {task_id}

                ## Prompt
                {prompt}

                ## Context (from Airbyte/Slack)
                {context or "No prior context available."}

                ## Database
                Connection string: `{conn_str}`
                Use this Postgres DB for all persistence in this task.
            """)
        )
        return spec_path

    def _kiro_spec(self, spec_path: Path) -> None:
        """Run `kiro spec <path>` to generate design doc + task queue."""
        result = subprocess.run(
            [cfg.kiro_cli_path, "spec", str(spec_path)],
            capture_output=True, text=True, cwd=spec_path.parent
        )
        if result.returncode != 0:
            raise RuntimeError(f"[Sean] kiro spec failed:\n{result.stderr}")
        print(f"[Sean] Spec processed → tasks generated")

    def _kiro_run(self, spec_path: Path) -> None:
        """Run `kiro run` to execute all tasks in the queue."""
        result = subprocess.run(
            [cfg.kiro_cli_path, "run", "--spec", str(spec_path), "--headless"],
            capture_output=True, text=True, cwd=spec_path.parent
        )
        if result.returncode != 0:
            raise RuntimeError(f"[Sean] kiro run failed:\n{result.stderr}")
        print(f"[Sean] All tasks executed")

    # ── GitHub PR ─────────────────────────────────────────────────────────

    def _open_pr(self, branch: str, task_id: str, prompt: str) -> str:
        resp = httpx.post(
            f"https://api.github.com/repos/{cfg.github_repo}/pulls",
            json={
                "title": f"[Shipify] {task_id}: {prompt[:60]}",
                "head": branch,
                "base": "main",
                "body": (
                    f"Automated PR by Sean (Shipify Developer Agent)\n\n"
                    f"**Task:** {task_id}\n**Prompt:** {prompt}\n\n"
                    f"_Awaiting Christopher's security review._"
                ),
            },
            headers={
                "Authorization": f"token {cfg.github_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["html_url"]
