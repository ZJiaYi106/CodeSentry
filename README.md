# CodeSentry

AI Coding Agent — analyze, plan, and modify code repositories with multi-agent safety controls.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │Task Plan │ │Timeline  │ │Tool Calls│ │Diff & Results │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ REST + SSE (real-time streaming)
┌──────────────────────┴──────────────────────────────────────┐
│                    FastAPI Backend                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Orchestrator Agent                       │   │
│  │  Planner → Analyst → Implementer → Reviewer → Done   │   │
│  │            (read-only)  (write-gated)  (exec-gated)  │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │Tools (6) │ │Security  │ │Memory    │ │Prompt Cache  │   │
│  │list_files│ │RBAC+Risk │ │Short-term│ │Redis/memory   │   │
│  │search_cd │ │+Audit    │ │ChromaDB  │ │hit/miss logs  │   │
│  │read_file │ │+Approve  │ │+Compress │ │               │   │
│  │write_ptch│ │          │ │          │ │               │   │
│  │run_tests │ │          │ │          │ │               │   │
│  │git_diff  │ │          │ │          │ │               │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                 Infrastructure                              │
│  ┌────────┐ ┌────────┐ ┌──────────┐                        │
│  │PostgreSQL│ │ChromaDB│ │Redis     │  Docker Compose       │
│  │(Audit)  │ │(Vector)│ │(Cache)   │                        │
│  └────────┘ └────────┘ └──────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+ (for frontend)
- Docker & Docker Compose (optional, for full deployment)

### Local Development

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your MODEL_API_KEY

# 2. Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev

# 4. Open http://localhost:5173
```

### Docker Compose

```bash
cp .env.example .env
docker-compose up -d
curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0","provider":"openai","model":"gpt-4o"}
```

### Run Demos (no API key needed)

```bash
cd backend
python ../demos/demo1_fix_typo/run_demo.py
python ../demos/demo2_add_docstring/run_demo.py
python ../demos/demo3_refactor/run_demo.py
```

All three demos demonstrate the full agent pipeline without requiring an LLM API key (rule-based fallback).

## Permission Model

| Risk Level | Tools | Auto-Approved | Requires Approval |
|------------|-------|:---:|:---:|
| **low** | `list_files`, `search_code`, `read_file`, `git_diff` | Yes | No |
| **medium** | `run_tests` | No | Yes (UI card) |
| **high** | `write_patch` | No | Yes (UI card) |

Configurable via `AUTO_APPROVE_RISK_LEVEL` in `.env` (`low` / `medium` / `high` / `none`).

## Multi-Agent Tool Isolation

| Sub-Agent | list_files | search_code | read_file | write_patch | run_tests | git_diff |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|
| **Analyst** (read-only) | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Implementer** (write-gated) | ❌ | ❌ | ✅ | ✅* | ❌ | ❌ |
| **Reviewer** (exec-gated) | ❌ | ❌ | ✅ | ❌ | ✅* | ✅ |

`*` = requires Orchestrator approval. No sub-agent has read + write + execute simultaneously.

## Data Flow

```
User Task → POST /api/v1/tasks
  → Orchestrator searches long-term memory (ChromaDB)
  → Analyst explores repo (list_files, search_code, read_file)
  → Implementer proposes changes (write_patch → approval required)
  → Reviewer validates (run_tests → approval required)
  → Summarizer produces final report
  → extract_and_store_insights() → ChromaDB (for future tasks)
  → SSE events stream to frontend (plan, tool_calls, approvals, summary)
```

## Agent Query Loop (LangGraph)

```
START → Planner → [tool calls?] → Tool Executor → Observation
       → Reflector → [continue | replan | finish]
            replan → Planner
            finish → Summarizer → END

Long-term memory injected into Planner prompt before each planning cycle.
Context compressed when estimated tokens exceed threshold (default 8000).
```

## Memory System

| Type | Storage | Content | Trigger |
|------|---------|---------|---------|
| Short-term | LangGraph State | Task state, tool observations, plan steps | Every node execution |
| Long-term | ChromaDB (3 collections) | Fix patterns, conventions, preferences | After task completion + on new task retrieval |
| Compression | LLM summary + truncation | Compresses old messages into dense summary | When estimated tokens > 8000 |

## Configuration

See `.env.example` for all options. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_PROVIDER` | `openai` / `anthropic` / `hermes` | `openai` |
| `MODEL_NAME` | Model identifier | `gpt-4o` |
| `MODEL_BASE_URL` | API base URL | `https://api.openai.com/v1` |
| `MODEL_API_KEY` | API key | — |
| `MAX_ITERATIONS` | Max agent loop iterations | `15` |
| `WORKSPACE_ROOT` | Sandbox root path | `/workspace` |
| `AUTO_APPROVE_RISK_LEVEL` | Auto-approve threshold | `low` |
| `CONTEXT_COMPRESSION_THRESHOLD_TOKENS` | Compression trigger | `8000` |
| `PROMPT_CACHE_ENABLED` | Enable prompt caching | `true` |

## Model Provider Switching

No provider is hardcoded. Switch via env vars:

```bash
# OpenAI
MODEL_PROVIDER=openai
MODEL_NAME=gpt-4o
MODEL_BASE_URL=https://api.openai.com/v1

# Anthropic Claude
MODEL_PROVIDER=anthropic
MODEL_NAME=claude-sonnet-5-20251001
MODEL_BASE_URL=https://api.anthropic.com

# Local Hermes / any OpenAI-compatible
MODEL_PROVIDER=hermes
MODEL_NAME=hermes-3
MODEL_BASE_URL=http://localhost:8080/v1
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check + provider info |
| `POST` | `/api/v1/tasks` | Submit a task |
| `GET` | `/api/v1/tasks` | List all tasks |
| `GET` | `/api/v1/tasks/{id}` | Get task status/results |
| `GET` | `/api/v1/tasks/{id}/stream` | SSE event stream |
| `POST` | `/api/v1/tasks/{id}/approve` | Approve/reject action |

## Project Structure

```
CodeSentry/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry
│   │   ├── config.py            # Env-based configuration
│   │   ├── db.py                # PostgreSQL (SQLAlchemy async)
│   │   ├── agents/              # Agent implementations
│   │   │   ├── orchestrator.py  # Multi-agent coordinator
│   │   │   ├── graph.py         # LangGraph StateGraph
│   │   │   ├── planner.py       # Task planner (+ memory injection)
│   │   │   ├── reflector.py     # Outcome evaluator
│   │   │   ├── summarizer.py    # Final report generator
│   │   │   ├── repo_analyst.py  # Read-only code explorer
│   │   │   ├── implementer.py   # Write-gated modifier
│   │   │   ├── reviewer.py      # Exec-gated tester
│   │   │   ├── base_agent.py    # Sub-agent base class
│   │   │   └── prompts.py       # System prompts
│   │   ├── tools/               # 6 tool implementations
│   │   │   ├── base.py          # Abstract tool + ToolResult
│   │   │   ├── registry.py      # Tool lookup
│   │   │   ├── file_list.py     # Directory listing
│   │   │   ├── code_search.py   # Regex code search
│   │   │   ├── read_file.py     # File reader
│   │   │   ├── write_patch.py   # Controlled file write
│   │   │   ├── run_tests.py     # Test executor
│   │   │   └── git_diff.py      # Git diff viewer
│   │   ├── security/            # Safety layer
│   │   │   └── permissions.py   # Whitelist, risk, approval
│   │   ├── memory/              # Memory system
│   │   │   ├── short_term.py    # AgentState, PlanStep
│   │   │   ├── long_term.py     # ChromaDB vector store
│   │   │   └── compressor.py    # Context compression
│   │   ├── models/              # LLM abstraction
│   │   │   ├── provider.py      # OpenAI/Anthropic/Hermes factory
│   │   │   └── cache.py         # Prompt cache (Redis + memory)
│   │   ├── audit/               # Audit logging
│   │   │   └── logger.py        # Event recorder
│   │   └── api/                 # HTTP layer
│   │       ├── routes.py        # REST + SSE endpoints
│   │       └── schemas.py       # Pydantic models
│   └── tests/                   # Test suite (152 tests)
│       ├── test_basic.py        # Health + config
│       ├── test_tools.py        # 6 tools + registry
│       ├── test_security.py     # Permissions + approval
│       ├── test_audit.py        # Audit logging
│       ├── test_agent.py        # Planner/Reflector/Graph
│       ├── test_models.py       # Provider + cache
│       ├── test_memory.py       # Short/long-term + compressor
│       ├── test_multi_agent.py  # Sub-agents + orchestrator
│       ├── test_long_term_memory.py # ChromaDB CRUD
│       ├── test_api.py          # REST endpoints
│       ├── test_demos.py        # Demo integration tests
│       └── conftest.py          # Shared fixtures
├── frontend/
│   └── src/
│       ├── App.tsx / App.css    # Main layout + dark theme
│       ├── hooks/useSSE.ts      # SSE streaming hook
│       ├── components/          # 6 UI components
│       └── types/index.ts       # TypeScript types
├── demos/                       # 3 reproducible demos
│   ├── demo1_fix_typo/
│   ├── demo2_add_docstring/
│   └── demo3_refactor/
├── docker-compose.yml           # 6-service orchestration
├── .env.example                 # All config options
└── README.md
```

## Testing

```bash
cd backend
python -m pytest tests/ -v

# 152 tests covering:
#   - 6 tools + path traversal prevention
#   - Security whitelist + risk classification + approval flow
#   - Audit logging (event recording, truncation, limits)
#   - LangGraph graph compilation + routing logic
#   - Planner/Reflector/Summarizer (LLM + fallback modes)
#   - Model provider factory (3 providers + caching)
#   - Prompt cache (hit/miss/invalidation)
#   - Short-term memory (AgentState, PlanStep)
#   - Long-term memory (ChromaDB CRUD, search, fallback)
#   - Context compression (token estimation, threshold trigger)
#   - Multi-agent orchestration (analyst/implementer/reviewer)
#   - Tool isolation (no agent has all 6 tools)
#   - REST API (task CRUD, approval, error handling)
#   - Memory retrieval injection (Planner + Orchestrator)
#   - 3 demo integration tests (end-to-end)
```

## Limitations & Risks

- **Model dependency**: Agent code-change quality is bounded by the underlying LLM. Fallback mode demonstrates the pipeline but doesn't actually modify code.
- **Safety**: Path traversal is blocked; write/exec require approval. However, `write_patch` is only safe if the LLM output is correct — always review patches before approving.
- **Cost**: Each agent loop calls the LLM. Set `MAX_ITERATIONS` conservatively for paid APIs.
- **Determinism**: LLM outputs are non-deterministic. Same task may produce different plans.
- **Local-only**: Designed for single-user local/dev use. Not hardened for multi-tenant production.
- **ChromaDB embedding**: Uses local `all-MiniLM-L6-v2` model (first run downloads ~80MB). Falls back to keyword search if unavailable.
- **SSE (Server-Sent Events)**: Simpler than WebSockets but unidirectional. The UI polls for task completion; real approval flow requires the SSE connection to remain open.

## License

MIT
