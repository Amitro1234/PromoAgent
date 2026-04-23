"""Agent definitions — PromoRetriever → PromoAnswer.

Two-stage pipeline adapted from the Microsoft Agent Framework geekacademy
reference (msftse/microsoft-agent-framework-geekacademy):

  PromoRetriever  — routes the query, searches both Azure AI Search indexes,
                    returns structured context with citations.
  PromoAnswer     — receives the question + retrieved context from the
                    conversation, generates a grounded Hebrew answer.

Agents are registered as persistent resources in Azure AI Foundry via
AzureAIProjectAgentProvider.create_agent().

Note: create_agent() is async and uses aiohttp internally.
      If aiohttp is not available (e.g. blocked by corporate proxy), register
      the agents manually in the Foundry portal using the instruction strings
      exported below (RETRIEVER_INSTRUCTIONS, ANSWER_INSTRUCTIONS).
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Instructions — exported so publish.py and the portal setup guide can use them
# ---------------------------------------------------------------------------

RETRIEVER_INSTRUCTIONS = """\
You are the data retrieval specialist for the Promo department internal agent.

Your ONLY job is to search and return raw data — do NOT produce a final answer.

Steps:
1. Read the user question carefully.
2. Decide which sources to search:
   - Questions about ratings, averages, peaks, rankings, season stats, numeric data
     → call search_excel_ratings
   - Questions about strategy, slogans, briefs, quotes, campaign phrasing, marketing
     → call search_word_strategy
   - Questions that need both (e.g. "best-performing season AND its strategy")
     → call BOTH tools
3. Call the relevant tool(s) with the original Hebrew question as the query.
4. Return ALL retrieved results verbatim — do not summarise, filter, or answer.
   Format your response as:

   RETRIEVAL RESULTS
   =================
   [paste tool output here, labelled by source]

Do NOT greet the user. Do NOT answer the question. Just retrieve and return data.
"""

# Load system_prompt.txt as the answer agent's instructions
_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "app" / "system_prompt.txt"
ANSWER_INSTRUCTIONS = (
    _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    if _SYSTEM_PROMPT_PATH.exists()
    else "You are an internal AI assistant for the Promo department. Answer in Hebrew."
)


# ---------------------------------------------------------------------------
# Async agent factory functions (require aiohttp + agent_framework)
# ---------------------------------------------------------------------------

async def create_retriever(
    provider,
    model: str | None = None,
):
    """Register PromoRetriever in Azure AI Foundry.

    Equipped with two Azure AI Search tools so it can fetch Excel ratings
    and Word strategy documents on demand.

    Requires: pip install agent-framework-foundry aiohttp
    """
    from pipeline.tools import search_excel_ratings, search_word_strategy

    return await provider.create_agent(
        name="PromoRetriever",
        model=model,
        instructions=RETRIEVER_INSTRUCTIONS,
        tools=[search_excel_ratings, search_word_strategy],
    )


async def create_answer_agent(
    provider,
    model: str | None = None,
):
    """Register PromoAnswer in Azure AI Foundry.

    Receives the question + retrieval results from the shared conversation
    and produces a grounded Hebrew answer following system_prompt.txt rules.

    Requires: pip install agent-framework-foundry aiohttp
    """
    return await provider.create_agent(
        name="PromoAnswer",
        model=model,
        instructions=ANSWER_INSTRUCTIONS,
    )
