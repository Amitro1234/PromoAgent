# PromoAgent

An internal RAG (Retrieval-Augmented Generation) agent for the Promo department at Keshet.  
Answers questions in Hebrew from two structured data sources:

- **Excel files** — broadcast ratings, season statistics, episode-level metrics (`tv-promos` index)
- **Word documents** — strategy briefs, campaign slogans, marketing phrasing (`word-docs` index)

The system routes each question to the right source automatically and returns grounded, cited answers — no hallucinations.

---

## Architecture

```
User question (Hebrew)
        │
        ▼
┌─────────────────┐
│  Query Router   │  rule-based: excel_numeric / word_quote / hybrid / unknown
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Azure AI Search (Retrieval)    │
│  • tv-promos index  (Excel)     │
│  • word-docs index  (Word)      │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────┐
│  Prompt Builder │  system_prompt.txt + route-specific addendum
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Chat Provider  │  azure_openai (default) | foundry (Agent Framework)
└────────┬────────┘
         │
         ▼
  Grounded Hebrew answer + source citations
```

### Key files

| Path | Role |
|------|------|
| `app/agent.py` | CLI entry point |
| `app/service.py` | Core RAG pipeline (`run_query`) |
| `app/api.py` | FastAPI service — `POST /query`, `GET /health` |
| `app/query_router.py` | Rule-based query classifier |
| `app/prompts.py` | Prompt assembly (system + route addendum) |
| `app/system_prompt.txt` | Base system prompt (policy source of truth) |
| `app/chat_provider.py` | Provider abstraction: Azure OpenAI or Foundry |
| `app/models.py` | Pydantic request/response models |
| `app/search_word_docs.py` | Azure AI Search helpers |
| `scripts/` | Index creation, ingestion, diagnostics |
| `tests/test_agent.py` | Regression test suite (router + live LLM) |

---

## Prerequisites

- Python 3.10+
- Azure subscription with:
  - **Azure OpenAI** — embeddings deployment + chat deployment
  - **Azure AI Search** — `tv-promos` and `word-docs` indexes
  - **Azure Blob Storage** — Excel and Word source files
- (Optional) Azure AI Foundry project — for the Foundry chat provider

---

## Setup

### 1. Clone and create virtual environment

```bash
git clone https://github.com/Amitro1234/PromoAgent.git
cd PromoAgent
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Corporate network note:** If `zipp` / `importlib-metadata` are blocked by a proxy,
> install the Foundry-related packages with `--no-deps`:
> ```bash
> pip install agent-framework-core agent-framework-openai agent-framework-foundry \
>             azure-ai-inference azure-ai-projects azure-identity \
>             opentelemetry-api importlib-metadata msal --no-deps
> ```

### 3. Configure environment

```bash
cp .env.example .env
# Fill in your values in .env — never commit this file
```

Required variables:

| Variable | Description |
|----------|-------------|
| `AZURE_SEARCH_ENDPOINT` | Azure AI Search service URL |
| `AZURE_SEARCH_KEY` | Admin API key |
| `AZURE_OPENAI_ENDPOINT` | Embeddings resource endpoint |
| `AZURE_OPENAI_KEY` | Embeddings API key |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model name |
| `AZURE_OPENAI_CHAT_ENDPOINT` | Chat resource endpoint |
| `AZURE_OPENAI_CHAT_KEY` | Chat API key |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Chat model deployment name |

---

## Running

### CLI — interactive REPL

```powershell
.venv\Scripts\python.exe -m app.agent
```

Type your question in Hebrew at the `שאלה:` prompt. Press Enter twice to exit.

### CLI — single question

```powershell
.venv\Scripts\python.exe -m app.agent "מה הרייטינג הממוצע של חתונה ממבט ראשון?"
```

Add `--debug` for full retrieval trace:

```powershell
.venv\Scripts\python.exe -m app.agent --debug "מה הסלוגן של עונה 3?"
```

### API server

```bash
uvicorn app.api:app --reload --host 0.0.0.0 --port 8000
```

Then:

```bash
curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"question": "מה הרייטינג הממוצע של חתונה ממבט ראשון?"}'
```

API response shape:

```json
{
  "answer": "...",
  "route": "excel_numeric",
  "confidence": "high",
  "sources": [{ "type": "excel", "title": "מעקבי פרומו.xlsx", "reference": "...", "score": 0.95 }],
  "trace_id": "uuid"
}
```

Health check: `GET /health`

---

## Chat Provider

Controlled by the `CHAT_PROVIDER` environment variable:

| Value | Description |
|-------|-------------|
| `azure_openai` | Default. Uses `AZURE_OPENAI_CHAT_*` variables + openai SDK |
| `foundry` | Microsoft Agent Framework via `FoundryChatClient` |

### Switching to Foundry

```env
CHAT_PROVIDER=foundry
AZURE_AI_PROJECT_ENDPOINT=https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<deployment-name>
AZURE_CREDENTIAL_TYPE=cli          # cli (local) | managed_identity (Azure-hosted)
```

Run `az login` before using `cli` credential locally.

---

## Tests

```bash
# Fast offline tests (router only — no LLM calls)
python -m pytest tests/ -m "not live" -v

# Full live tests (LLM + retrieval — costs tokens)
python -m pytest tests/ -v
```

---

## Deployment to Azure AI Foundry

### Option A — Foundry Agent Playground (no-code)

1. Open [Azure AI Foundry](https://ai.azure.com) and navigate to your project.
2. Go to **Agents** → **Create agent**.
3. Select your GPT-4o deployment.
4. Paste the contents of `app/system_prompt.txt` into the **Instructions** field.
5. Set `CHAT_PROVIDER=foundry` in your environment and configure `AZURE_AI_PROJECT_ENDPOINT`.

### Option B — API on Azure App Service

```bash
# Build and deploy
az webapp up --name promo-agent --runtime "PYTHON:3.12" --sku B1

# Set environment variables in App Service
az webapp config appsettings set --name promo-agent --settings \
  AZURE_SEARCH_ENDPOINT="..." \
  AZURE_OPENAI_CHAT_ENDPOINT="..." \
  # ... all required vars
```

Startup command:

```
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

### Option C — Container (Docker)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Security notes

- `.env` is git-ignored — never commit it.
- All secrets are read from environment variables at runtime.
- For production: replace the `AZURE_OPENAI_CHAT_KEY` with **Managed Identity** auth.
- The API has a CORS placeholder and an Entra ID auth stub in `app/api.py` — wire these before exposing to SharePoint.

---

## Project structure

```
PromoAgent/
├── app/
│   ├── agent.py            # CLI entry point
│   ├── api.py              # FastAPI service
│   ├── chat_provider.py    # Provider abstraction (Azure OpenAI / Foundry)
│   ├── models.py           # Pydantic models
│   ├── prompts.py          # Prompt assembly
│   ├── query_router.py     # Rule-based router
│   ├── search_word_docs.py # Azure AI Search helpers
│   ├── service.py          # Core RAG pipeline
│   └── system_prompt.txt   # Base system prompt
├── scripts/                # Index creation & ingestion utilities
├── tests/
│   └── test_agent.py       # Regression test suite
├── .env.example            # Environment variable template
├── requirements.txt
└── README.md
```
