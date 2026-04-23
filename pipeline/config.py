"""Configuration loader — reads .env and validates required settings.

Reuses the same environment variables as app/ so a single .env file
drives both the RAG service layer and the Foundry pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    model_deployment: str
    # Publishing to Foundry as an Agent Application (optional)
    subscription_id: str | None = None
    resource_group: str | None = None


def load_settings() -> Settings:
    """Load settings from environment / .env file."""
    load_dotenv()

    endpoint = (
        os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        or os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
    )
    deployment = (
        os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        or os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4o-1")
    )

    if not endpoint:
        raise EnvironmentError(
            "AZURE_AI_PROJECT_ENDPOINT is required. Check your .env file."
        )

    return Settings(
        project_endpoint=endpoint,
        model_deployment=deployment,
        subscription_id=os.environ.get("AZURE_SUBSCRIPTION_ID") or None,
        resource_group=os.environ.get("AZURE_RESOURCE_GROUP") or None,
    )
