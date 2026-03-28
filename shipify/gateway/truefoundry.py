"""
TrueFoundry agent gateway — observability + cost governance.

Wraps every agent call to:
  - Record token usage and latency per agent
  - Enforce per-agent USD budget quotas
  - Surface real-time spend to the TrueFoundry dashboard
"""
import time
import httpx
from typing import Callable, Any
from shipify.config import cfg


class TrueFoundryGateway:
    """Records metrics and enforces budgets for each agent invocation."""

    def __init__(self):
        self._base = cfg.truefoundry_gateway_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {cfg.truefoundry_api_key}",
            "Content-Type": "application/json",
        }
        # In-memory spend tracker (also pushed to TrueFoundry)
        self._spend: dict[str, float] = {
            "developer": 0.0,
            "tester": 0.0,
            "deployer": 0.0,
        }
        self._budgets: dict[str, float] = {
            "developer": cfg.developer_budget_usd,
            "tester": cfg.tester_budget_usd,
            "deployer": cfg.deployer_budget_usd,
        }

    def check_budget(self, agent: str) -> None:
        """Raise if the agent has exceeded its budget."""
        spent = self._spend.get(agent, 0.0)
        budget = self._budgets.get(agent, float("inf"))
        if spent >= budget:
            raise RuntimeError(
                f"[TrueFoundry] Budget exceeded for '{agent}': "
                f"${spent:.4f} / ${budget:.2f}"
            )

    def record(self, agent: str, tokens_in: int, tokens_out: int,
               latency_ms: float, tool: str = "", error: bool = False) -> None:
        """Push a usage event to TrueFoundry and update local spend."""
        # Rough cost estimate: $0.15/1M input, $0.60/1M output (GPT-4o pricing)
        cost = (tokens_in * 0.15 + tokens_out * 0.60) / 1_000_000
        self._spend[agent] = self._spend.get(agent, 0.0) + cost

        payload = {
            "agent": agent,
            "tool": tool,
            "tokens_input": tokens_in,
            "tokens_output": tokens_out,
            "cost_usd": cost,
            "latency_ms": latency_ms,
            "error": error,
        }
        try:
            httpx.post(
                f"{self._base}/metrics",
                json=payload,
                headers=self._headers,
                timeout=5,
            )
        except Exception:
            pass  # Non-blocking — metrics loss is acceptable

        status = "ERROR" if error else "OK"
        print(
            f"[TrueFoundry] {agent} | {tool or 'llm'} | "
            f"in={tokens_in} out={tokens_out} | "
            f"${cost:.5f} | {latency_ms:.0f}ms | {status}"
        )

    def tracked(self, agent: str, tool: str = "") -> Callable:
        """Decorator factory — wraps any agent function with budget + metrics."""
        def decorator(fn: Callable) -> Callable:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                self.check_budget(agent)
                start = time.monotonic()
                error = False
                try:
                    result = fn(*args, **kwargs)
                    return result
                except Exception as exc:
                    error = True
                    raise exc
                finally:
                    latency = (time.monotonic() - start) * 1000
                    # Token counts extracted from result if available
                    tokens_in = getattr(result if not error else None, "usage", None)
                    self.record(
                        agent=agent,
                        tokens_in=getattr(tokens_in, "prompt_tokens", 0) if tokens_in else 0,
                        tokens_out=getattr(tokens_in, "completion_tokens", 0) if tokens_in else 0,
                        latency_ms=latency,
                        tool=tool,
                        error=error,
                    )
            return wrapper
        return decorator

    def spend_report(self) -> dict[str, float]:
        return dict(self._spend)


gateway = TrueFoundryGateway()
