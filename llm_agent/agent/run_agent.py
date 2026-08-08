"""Backward-compatible entry point; application startup lives in app/."""

from llm_agent.app.run_agent import main


if __name__ == "__main__":
    main()
