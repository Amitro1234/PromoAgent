"""
api.py

FastAPI application for the Promo department agent.

Endpoints
---------
    GET  /health       — liveness / readiness check
    POST /query        — main question-answering endpoint

Running locally
---------------
    uvicorn app.api:app --reload --host 0.0.0.0 --port 8000

Environment variables
---------------------
    CORS_ORIGINS   comma-separated allowed origins, default "*" (restrict in production)
                   Example: https://yourtenant.sharepoint.com,https://yourtenant-admin.sharepoint.com
    API_HOST       bind address (default 0.0.0.0)
    API_PORT       port        (default 8000)

Authentication
--------------
    Entra ID bearer-token validation is NOT yet wired — a placeholder comment marks
    the insertion point.  Add azure-identity + a FastAPI dependency that validates
    the Authorization: Bearer <token> header before the /query handler runs.

SharePoint integration notes
-----------------------------
    1. Set CORS_ORIGINS to your SharePoint tenant domain(s).
    2. The response JSON is intentionally flat and JS-friendly.
    3. The trace_id field lets you correlate browser-side errors with server logs.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import ErrorResponse, QueryRequest, QueryResponse
from .service import run_query

load_dotenv()

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CORS — read allowed origins from env so nothing is hard-coded
# ---------------------------------------------------------------------------

_raw_origins = os.getenv("CORS_ORIGINS", "*")
_CORS_ORIGINS: list[str] = (
    ["*"] if _raw_origins.strip() == "*"
    else [o.strip() for o in _raw_origins.split(",") if o.strip()]
)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    log.info("Promo Agent API starting — CORS origins: %s", _CORS_ORIGINS)
    yield
    log.info("Promo Agent API shutting down")


app = FastAPI(
    title="Promo Agent API",
    version="1.0.0",
    description="Internal RAG agent for the Promo department. Answers questions from Excel and Word sources.",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


# ---------------------------------------------------------------------------
# Auth placeholder
# ---------------------------------------------------------------------------
# TODO: Replace this stub with real Entra ID token validation when ready.
#
# Pattern to follow:
#   from fastapi import Security
#   from fastapi.security import OAuth2AuthorizationCodeBearer
#   oauth2_scheme = OAuth2AuthorizationCodeBearer(...)
#
#   async def verify_token(token: str = Security(oauth2_scheme)):
#       # validate token with azure-identity or msal
#       ...
#
#   Then add   dependencies=[Security(verify_token)]
#   to the @app.post("/query") decorator below.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Exception handlers — always return the ErrorResponse envelope
# ---------------------------------------------------------------------------


@app.exception_handler(EnvironmentError)
async def env_error_handler(request: Request, exc: EnvironmentError) -> JSONResponse:
    log.error("Configuration error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ErrorResponse(error=str(exc)).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error processing request")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error="Internal server error — check server logs").model_dump(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
async def health() -> dict:
    """Liveness / readiness probe.

    Returns 200 when the service is running and config is present.
    Used by load balancers, Azure App Service health checks, etc.
    """
    cfg_ok = all([
        os.getenv("AZURE_OPENAI_CHAT_ENDPOINT"),
        os.getenv("AZURE_OPENAI_CHAT_KEY"),
        os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        os.getenv("AZURE_SEARCH_ENDPOINT"),
        os.getenv("AZURE_SEARCH_KEY"),
    ])
    if not cfg_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="One or more required environment variables are missing",
        )
    return {"status": "ok", "service": "promo-agent", "version": app.version}


@app.post(
    "/query",
    response_model=QueryResponse,
    tags=["agent"],
    summary="Ask the Promo Agent a question",
    response_description="Grounded answer with source citations and routing metadata",
)
def query(req: QueryRequest) -> QueryResponse:
    """Run the full RAG pipeline and return a structured answer.

    Declared as a plain ``def`` (not ``async def``) so FastAPI automatically
    runs it in a thread-pool via ``run_in_executor``.  This prevents the
    synchronous LLM call from blocking the uvicorn event loop.

    - `question` — the user's question in Hebrew (or any language)
    - `debug`    — when true, `debug_trace` in the response contains the full
                   retrieved context that was sent to the LLM

    **Response fields**

    | Field         | Description |
    |---------------|-------------|
    | `answer`      | Grounded Hebrew answer |
    | `route`       | Router classification (`excel_numeric` / `word_quote` / `hybrid` / `unknown`) |
    | `confidence`  | `high` / `medium` / `low` based on retrieval scores |
    | `sources`     | List of cited documents with type, title, reference, and score |
    | `trace_id`    | UUID — correlate with server logs |
    | `debug_trace` | Full retrieval context (only when `debug=true`) |
    """
    log.info("POST /query  question=%r  debug=%s", req.question[:80], req.debug)
    return run_query(req.question, debug=req.debug)
