"""
Shipify — central config. All secrets come from environment variables.
"""
import os
from dataclasses import dataclass


@dataclass
class Config:
    # Kiro CLI
    kiro_cli_path: str = os.getenv("KIRO_CLI_PATH", "kiro")
    kiro_workspace: str = os.getenv("KIRO_WORKSPACE", "/tmp/shipify-workspace")

    # Macroscope
    macroscope_slack_token: str = os.getenv("MACROSCOPE_SLACK_TOKEN", "")
    macroscope_slack_channel: str = os.getenv("MACROSCOPE_SLACK_CHANNEL", "#macroscope")
    macroscope_webhook_secret: str = os.getenv("MACROSCOPE_WEBHOOK_SECRET", "")

    # TrueFoundry
    truefoundry_api_key: str = os.getenv("TRUEFOUNDRY_API_KEY", "")
    truefoundry_workspace_fqn: str = os.getenv("TRUEFOUNDRY_WORKSPACE_FQN", "")
    truefoundry_gateway_url: str = os.getenv("TRUEFOUNDRY_GATEWAY_URL", "")

    # Ghost MCP
    ghost_mcp_url: str = os.getenv("GHOST_MCP_URL", "")
    ghost_mcp_token: str = os.getenv("GHOST_MCP_TOKEN", "")

    # Airbyte
    airbyte_api_key: str = os.getenv("AIRBYTE_API_KEY", "")
    airbyte_connection_id: str = os.getenv("AIRBYTE_CONNECTION_ID", "")  # Slack → vector store
    pinecone_api_key: str = os.getenv("PINECONE_API_KEY", "")
    pinecone_index: str = os.getenv("PINECONE_INDEX", "shipify-context")

    # GitHub (for PR creation)
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_repo: str = os.getenv("GITHUB_REPO", "")  # e.g. "org/repo"

    # Agent token budgets (USD)
    developer_budget_usd: float = float(os.getenv("DEVELOPER_BUDGET_USD", "5.0"))
    tester_budget_usd: float = float(os.getenv("TESTER_BUDGET_USD", "2.0"))
    deployer_budget_usd: float = float(os.getenv("DEPLOYER_BUDGET_USD", "1.0"))


cfg = Config()
