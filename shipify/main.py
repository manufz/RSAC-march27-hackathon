"""
Shipify — entry point.

Usage:
    python -m shipify.main "Add OAuth2 login with Google" --version 1.4.0
    python -m shipify.main "Refactor the payments module" --version 2.1.0
"""
import argparse
import sys
from shipify.orchestrator.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        prog="shipify",
        description="Autonomous multi-agent engineering platform.",
    )
    parser.add_argument("prompt", help="Natural-language feature description")
    parser.add_argument(
        "--version", default="0.1.0", help="Semver version string for this deployment"
    )
    args = parser.parse_args()

    result = run_pipeline(prompt=args.prompt, version=args.version)

    if result["status"] == "blocked":
        print("Pipeline blocked by security review. Fix the issues and re-run.")
        sys.exit(1)
    elif result["status"] == "rolled_back":
        print("Deployment failed health checks and was rolled back.")
        sys.exit(2)
    else:
        print(f"Shipped v{result['version']} successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
