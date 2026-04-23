"""Workflow builder — sequential pipeline: PromoRetriever → PromoAnswer.

Mirrors the pattern from msftse/microsoft-agent-framework-geekacademy:

    WorkflowBuilder(start_executor=retriever)
        .add_edge(retriever, answerer)
        .build()

The pipeline runs in two stages:
  1. PromoRetriever  — routes the Hebrew question, calls Azure AI Search tools,
                       returns raw cited context into the shared conversation.
  2. PromoAnswer     — reads the question + retrieval context from the
                       conversation, generates a grounded Hebrew answer.

Usage (async, requires aiohttp):
    pipeline = build_pipeline(retriever, answerer)
    async for event in pipeline.run(question, stream=True):
        ...

For Foundry deployment (no aiohttp needed):
    Use pipeline/publish.py to register promo-pipeline.yaml as a workflow
    agent in your Foundry project and invoke it via the portal or REST API.
"""

from __future__ import annotations

from agent_framework import AgentResponseUpdate, WorkflowBuilder


def build_pipeline(retriever, answerer):
    """Build the two-stage PromoAgent sequential workflow.

    Args:
        retriever:  PromoRetriever agent (created by pipeline.agents.create_retriever)
        answerer:   PromoAnswer agent   (created by pipeline.agents.create_answer_agent)

    Returns:
        A built Workflow object ready for pipeline.run(question, stream=True).
    """
    return (
        WorkflowBuilder(start_executor=retriever)
        .add_edge(retriever, answerer)
        .build()
    )
