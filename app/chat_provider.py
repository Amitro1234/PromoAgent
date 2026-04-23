"""
chat_provider.py

Provider abstraction for the chat/LLM execution layer only.

Everything upstream of this file (routing, retrieval, formatting, prompt
assembly) is unchanged.  Only the final "send messages → get text" step
is delegated to the provider selected by CHAT_PROVIDER.

Providers
---------
azure_openai  (default)
    Wraps the current Azure OpenAI path via the openai SDK.
    Auth: API key from AZURE_OPENAI_CHAT_KEY.

foundry
    Wraps Microsoft Agent Framework / FoundryChatClient.
    Auth: Azure credential (AzureCliCredential locally,
          ManagedIdentityCredential on Azure-hosted deployments).
    Requires: pip install agent-framework azure-identity

Environment variables
---------------------
CHAT_PROVIDER                   azure_openai | foundry  (default: azure_openai)
AZURE_CREDENTIAL_TYPE           cli | managed_identity  (default: cli, Foundry only)

Azure OpenAI provider
    AZURE_OPENAI_CHAT_ENDPOINT
    AZURE_OPENAI_CHAT_KEY
    AZURE_OPENAI_CHAT_DEPLOYMENT

Foundry provider (Agent Framework canonical names)
    AZURE_AI_PROJECT_ENDPOINT        Foundry project endpoint URL.
                                     Format: https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
                                     (NOT the old api.azureml.ms domain)
    AZURE_AI_MODEL_DEPLOYMENT_NAME   deployment name in Foundry

    Aliases accepted as fallbacks:
    FOUNDRY_PROJECT_ENDPOINT
    FOUNDRY_MODEL_DEPLOYMENT_NAME
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class ChatProvider(ABC):
    """Minimal contract: accept a messages list, return the answer string.

    The messages list is in standard OpenAI format:
        [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]

    build_messages() in prompts.py always produces exactly this shape.
    """

    @abstractmethod
    def complete(self, messages: list[dict]) -> str:
        """Send messages to the model and return the response text."""


# ---------------------------------------------------------------------------
# Azure OpenAI implementation  (current default)
# ---------------------------------------------------------------------------


class AzureOpenAIProvider(ChatProvider):
    """Azure OpenAI via the openai SDK — key-based auth, no changes to existing logic."""

    def __init__(self) -> None:
        missing = [v for v in [
            "AZURE_OPENAI_CHAT_ENDPOINT",
            "AZURE_OPENAI_CHAT_KEY",
            "AZURE_OPENAI_CHAT_DEPLOYMENT",
        ] if not os.getenv(v)]
        if missing:
            raise EnvironmentError(
                f"Missing env vars for azure_openai provider: {', '.join(missing)}"
            )
        self.endpoint   = os.environ["AZURE_OPENAI_CHAT_ENDPOINT"]
        self.api_key    = os.environ["AZURE_OPENAI_CHAT_KEY"]
        self.deployment = os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"]

    def complete(self, messages: list[dict]) -> str:
        from openai import OpenAI  # already in requirements.txt
        client = OpenAI(base_url=self.endpoint, api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            temperature=0,
            max_tokens=1500,
        )
        return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Microsoft Foundry implementation  (Agent Framework)
# ---------------------------------------------------------------------------


class FoundryProvider(ChatProvider):
    """Microsoft Foundry via Microsoft Agent Framework.

    Maps our two-message format to Agent Framework's (instructions, run) pattern:
        messages[0]["content"]  →  Agent.instructions  (system prompt)
        messages[1]["content"]  →  agent.run(...)       (user message + context)

    The async agent.run() is run in a dedicated thread so this method stays
    synchronous and is safe to call from both CLI and FastAPI contexts.
    """

    def __init__(self) -> None:
        # Accept both the Agent Framework canonical name and our own aliases
        self.project_endpoint = (
            os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
            or os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
            or ""
        )
        self.model = (
            os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
            or os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME")
            or ""
        )
        if not self.project_endpoint or not self.model:
            raise EnvironmentError(
                "Foundry provider requires:\n"
                "  AZURE_AI_PROJECT_ENDPOINT  (or FOUNDRY_PROJECT_ENDPOINT)\n"
                "  AZURE_AI_MODEL_DEPLOYMENT_NAME  (or FOUNDRY_MODEL_DEPLOYMENT_NAME)"
            )
        self._credential = None  # lazy init

    def _get_credential(self):
        """Return the Azure credential instance, created once per provider lifetime.

        AZURE_CREDENTIAL_TYPE=cli               → AzureCliCredential  (requires az login)
        AZURE_CREDENTIAL_TYPE=managed_identity  → ManagedIdentityCredential  (Azure-hosted)
        """
        if self._credential is not None:
            return self._credential

        try:
            from azure.identity import AzureCliCredential, ManagedIdentityCredential
        except ImportError as exc:
            raise ImportError(
                "azure-identity is required for the Foundry provider. "
                "Run: pip install azure-identity"
            ) from exc

        cred_type = os.getenv("AZURE_CREDENTIAL_TYPE", "cli").lower()
        if cred_type == "managed_identity":
            self._credential = ManagedIdentityCredential()
            log.info("Foundry auth: ManagedIdentityCredential")
        else:
            self._credential = AzureCliCredential()
            log.info("Foundry auth: AzureCliCredential (run 'az login' if not authenticated)")

        return self._credential

    def complete(self, messages: list[dict]) -> str:
        """Bridge sync call → async Agent Framework, safe from any context."""
        try:
            from agent_framework import Agent
            from agent_framework.foundry import FoundryChatClient
        except ImportError as exc:
            raise ImportError(
                "Microsoft Agent Framework is not installed. "
                "Run: pip install agent-framework"
            ) from exc

        # Our build_messages() always returns [system, user]
        system_msg = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        user_msg = next(
            (m["content"] for m in messages if m["role"] == "user"), ""
        )

        credential     = self._get_credential()
        project_endpoint = self.project_endpoint
        model          = self.model

        async def _run() -> str:
            agent = Agent(
                client=FoundryChatClient(
                    credential=credential,
                    project_endpoint=project_endpoint,
                    model=model,
                ),
                name="PromoAgent",
                instructions=system_msg,
            )
            result = await agent.run(user_msg)
            # Prefer the explicit .text attribute (mirrors streaming chunk.text).
            # Fall back to str() if the result type does not expose it — this
            # keeps the code forward-compatible if the Agent Framework response
            # type changes between SDK versions.
            text = getattr(result, "text", None)
            if not text:
                log.debug("FoundryProvider: result has no .text attribute, using str()")
                text = str(result)
            return text.strip()

        # Sync → async bridge strategy:
        #   asyncio.run() requires a thread with NO running event loop.
        #   A dedicated worker thread (ThreadPoolExecutor) always satisfies this:
        #   - CLI: the main thread has no event loop → the worker is clean.
        #   - FastAPI: the uvicorn event loop runs on the main thread; the worker
        #     thread has no loop → asyncio.run() starts a fresh one safely.
        #   Alternatives rejected:
        #     loop.run_until_complete()  — raises RuntimeError if loop already running
        #     nest_asyncio               — monkey-patches asyncio (fragile)
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _run()).result()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_provider() -> ChatProvider:
    """Read CHAT_PROVIDER and return the configured provider instance.

    Called once per request in service.run_query().
    """
    name = os.getenv("CHAT_PROVIDER", "azure_openai").lower()
    if name == "foundry":
        return FoundryProvider()
    return AzureOpenAIProvider()
