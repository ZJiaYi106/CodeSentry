# CodeSentry

AI Coding Agent — analyze, plan, and modify code repositories.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │Task Plan │ │Timeline  │ │Tool Calls│ │Diff & Results │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ REST + SSE
┌──────────────────────┴──────────────────────────────────────┐
│                    FastAPI Backend                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Orchestrator Agent                       │   │
│  │  Planner → Router → Sub-Agents → Reflection → Loop   │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │   │
│  │  │Repo Analyst  │ │Implementer   │ │Reviewer/Test │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │Tools (6) │ │Security  │ │Memory    │ │Prompt Cache  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                 Infrastructure                              │
│  ┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │PostgreSQL│ │ChromaDB│ │Redis     │ │Docker Compose    │   │
│  └────────┘ └────────┘ └──────────┘ └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local dev)
- Node.js 20+ (for frontend dev)

### Running with Docker Compose

```bash
# 1. Clone and enter
git clone <repo-url> && cd CodeSentry

# 2. Configure
cp .env.example .env
# Edit .env — set MODEL_PROVIDER, MODEL_API_KEY

# 3. Launch
docker-compose up -d

# 4. Verify
curl http://localhost:8000/health
# → {"status": "ok", "version": "0.1.0"}
```

### Running Locally (Backend)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp ../.env.example ../.env
uvicorn app.main:app --reload --port 8000
```

### Running Locally (Frontend)

```bash
cd frontend
npm install
npm run dev
```

## Permission Model

| Risk Level | Tool Examples | Auto-Approved? | Requires User Approval? |
|------------|---------------|----------------|------------------------|
| **low** | `list_files`, `search_code`, `read_file`, `git_diff` | Yes (configurable) | No |
| **medium** | `run_tests` | No | Yes (card in UI) |
| **high** | `write_patch`, `git_commit` | No | Yes (card in UI) |

All operations are restricted to `WORKSPACE_ROOT`. Any path traversal attempt is blocked.

## Data Flow

1. **User** sends task via REST API or UI
2. **Orchestrator** receives task → creates plan
3. **Repo Analyst** gathers context (read-only tools)
4. **Implementer** proposes changes (writes patches, requires approval)
5. **Reviewer/Tester** validates changes (runs tests, requires approval)
6. **Reflection** loop: evaluate → replan or continue
7. **Summarizer** compresses context, writes long-term memory
8. **Response** streamed back via SSE: plan, tool calls, approvals, diff, results

## Configuration

See `.env.example` for all options. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_PROVIDER` | `openai` / `anthropic` / `hermes` | `openai` |
| `MODEL_NAME` | Model identifier | `gpt-4o` |
| `MAX_ITERATIONS` | Max agent loop iterations | `15` |
| `WORKSPACE_ROOT` | Sandbox root path | `/workspace` |
| `AUTO_APPROVE_RISK_LEVEL` | Auto-approve up to this risk | `low` |

## Agent Query Loop

```
START → Planner → Tool Exec → Observation → Reflection → [continue|replan|finish]
         ↑                                                    |
         └────────────────────────────────────────────────────┘
```

## Memory System

- **Short-term**: LangGraph state — task status, tool observations, intermediate results
- **Long-term**: ChromaDB vector store — fix patterns, project conventions, user preferences
- **Compression**: Triggered when context exceeds 8000 tokens; LLM summarizes older turns

## Limitations & Risks

- **Model dependency**: Agent quality depends on the underlying LLM's code understanding
- **Safety**: Despite sandboxing, review high-risk patches before applying
- **Cost**: Each agent loop calls the LLM; set `MAX_ITERATIONS` conservatively
- **Determinism**: LLM outputs vary; same task may yield different plans
- **Local-only**: Designed for single-user local/dev use; not hardened for multi-tenant production

## Development Status

- [x] Phase 1: Project skeleton
- [ ] Phase 2: Tool layer + security
- [ ] Phase 3: Agent workflow (LangGraph)
- [ ] Phase 4: Multi-agent collaboration
- [ ] Phase 5: Memory + Prompt Cache + Audit
- [ ] Phase 6: API routes + Frontend
- [ ] Phase 7: Demos + Integration tests

## License

MIT
