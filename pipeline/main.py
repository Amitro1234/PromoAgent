"""Entry point — wires config, agents, and workflow together.

Two execution modes:
  1. Full async pipeline (PromoRetriever → PromoAnswer via WorkflowBuilder)
     Requires: aiohttp, agent-framework-foundry
     Run: python -m pipeline.main

  2. Fallback single-agent mode (existing service.py path, no aiohttp)
     Activated automatically when aiohttp is unavailable.
     Run: python -m pipeline.main --fallback

Usage
-----
    python -m pipeline.main
    python -m pipeline.main "מה הרייטינג הממוצע של חתונה ממבט ראשון?"
    python -m pipeline.main --fallback "שאלה כאן"
"""

from __future__ import annotations

import asyncio
import sys

from dotenv import load_dotenv

from pipeline.config import load_settings

DEFAULT_QUESTION = "מה הרייטינג הממוצע של חתונה ממבט ראשון?"


# ---------------------------------------------------------------------------
# Full async pipeline (PromoRetriever → PromoAnswer)
# ---------------------------------------------------------------------------

async def run_pipeline(question: str, settings) -> None:
    """Run the two-stage workflow using the Microsoft Agent Framework."""
    from azure.identity.aio import AzureCliCredential
    from agent_framework import AgentResponseUpdate
    from agent_framework.azure import AzureAIProjectAgentProvider

    from pipeline.agents import create_retriever, create_answer_agent
    from pipeline.workflow import build_pipeline

    credential = AzureCliCredential()

    async with AzureAIProjectAgentProvider(
        project_endpoint=settings.project_endpoint,
        credential=credential,
    ) as provider:
        print("Registering agents in Foundry ...")
        retriever = await create_retriever(provider, model=settings.model_deployment)
        answerer  = await create_answer_agent(provider, model=settings.model_deployment)

        pipeline = build_pipeline(retriever, answerer)

        print(f"\n{'=' * 60}")
        print(f"Question: {question}")
        print(f"{'=' * 60}\n")

        last_executor = None
        async for event in pipeline.run(question, stream=True):
            if event.type == "executor_invoked":
                exec_id = getattr(event, "executor_id", None)
                if exec_id and exec_id not in ("input-conversation", "end", None):
                    if last_executor:
                        print(f"\n{'-' * 40}")
                    print(f"\n[{exec_id}]:")
                    last_executor = exec_id

            if event.type == "output" and isinstance(event.data, AgentResponseUpdate):
                text = str(event.data)
                if text:
                    print(text, end="", flush=True)

        print(f"\n\n{'=' * 60}\nPipeline complete.")

    await credential.close()


# ---------------------------------------------------------------------------
# Fallback single-agent mode (no aiohttp needed)
# ---------------------------------------------------------------------------

def run_fallback(question: str) -> None:
    """Run the existing service.py pipeline (sync, no aiohttp required)."""
    from app.service import run_query

    print(f"\n[Fallback mode — using service.py directly]\n")
    result = run_query(question)
    print(f"Answer:\n{result.answer}")
    print(f"\n[route={result.route}  confidence={result.confidence}  sources={len(result.sources)}]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    settings = load_settings()

    import argparse
    ap = argparse.ArgumentParser(description="PromoAgent pipeline CLI")
    ap.add_argument("question", nargs="?", default=None, help="Question in Hebrew")
    ap.add_argument("--fallback", action="store_true",
                    help="Skip agent framework, use service.py directly")
    args = ap.parse_args()

    question = args.question or DEFAULT_QUESTION

    if args.fallback:
        run_fallback(question)
        return

    try:
        asyncio.run(run_pipeline(question, settings))
    except ImportError as exc:
        print(f"\naiohttp or agent-framework-foundry not available: {exc}")
        print("Falling back to service.py (sync mode)...\n")
        run_fallback(question)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
