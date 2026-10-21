# HiveOps

[![CI](https://github.com/YOUR-USERNAME/hiveops/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR-USERNAME/hiveops/actions/workflows/ci.yml)

A platform where a team of AI agents completes business tasks together. Upload documents, connect data, and delegate work: a Supervisor plans it, specialist agents research, analyse, write and review, and anything with side effects (an email, a Slack post) waits for a human to approve it. Every step streams live to a command-center dashboard, and evaluation suites measure answer quality.

**Stack:** React · TypeScript · Tailwind CSS · FastAPI · LangGraph · PostgreSQL + pgvector · Redis · Docker

## Features

| Area | What it does |
|------|--------------|
| **Multi-agent orchestration** | A LangGraph state machine runs six agents: Supervisor, Research Agent, Data Analyst, Report Writer, QA Reviewer and Comms Agent. In **autopilot** mode, the Supervisor plans each run and routes steps to specialists. In **pipeline** mode, the steps come from the workflow builder. |
| **RAG** | Upload PDF, Markdown or text files. They are chunked by section, embedded, and stored in pgvector with an HNSW cosine index. Retrieval is hybrid: vector similarity for recall, then a keyword-overlap rerank. Answers cite their source documents. |
| **Tool calling** | Agents call typed tools: `search_documents`, `list_datasets`, `describe_dataset`, `query_dataset` (aggregate, group and filter), `calculator` (a safe AST evaluator), `send_email` and `post_slack_message`. Each agent may only use its own tools. |
| **Human approvals** | Side-effect tools and any step marked "requires approval" pause the graph with LangGraph `interrupt()`. State is checkpointed in PostgreSQL, so a run resumes after the decision, even on another worker. Approved actions execute exactly once, rejected ones never do, and double decisions are refused. |
| **Live execution logs** | Every LLM call, tool call, result, approval and output is stored as an ordered, gap-free audit log and streamed to the browser over Server-Sent Events (Redis pub/sub across processes). Reconnecting resumes from the last event. |
| **Workflow builder** | Create pipelines step by step: choose an agent, give it an instruction, add approval gates, reorder steps, and see a live preview. Four templates are included. |
| **Evaluation dashboards** | Test suites score retrieval hit rate, answer recall, groundedness, latency and cost per case, with a history chart. |
| **Observability** | Token usage and cost are tracked per LLM call, rolled up per run and per agent. The command center shows spend, success rate, approval rate, a live agent routing map, agent health and a cost trend. |
| **Enterprise integrations** | Approved emails are written to an outbox (an audit trail for side effects), and Slack posts go to a real webhook when `SLACK_WEBHOOK_URL` is set. CSV upload connects datasets. |
| **Reliability** | Async workers pull jobs from a Redis queue. LLM calls are retried, and failures fail the run cleanly with the reason. Malformed supervisor plans fall back to a safe default. Runs interrupted by a restart are recovered. Uploads are validated and size-limited. |

## Run Without an API Key

HiveOps works out of the box with a **simulated LLM**: a deterministic, offline model with the same tool-calling interface as a real one. It plans by keyword, writes extractive summaries and templated reports, and is clearly labelled in the UI. This keeps the demo and the test suite free and reproducible.

To use a real model, set one of these before starting the server:

```bash
ANTHROPIC_API_KEY=sk-ant-...          # Claude (ANTHROPIC_MODEL, default claude-haiku-5-5)
OPENAI_API_KEY=sk-...                 # OpenAI (OPENAI_MODEL, default gpt-4o-mini)
OPENAI_BASE_URL=http://localhost:11434/v1   # or any OpenAI-compatible server, e.g. Ollama
```

## Architecture

```
 React UI ──REST──▶ FastAPI ──enqueue──▶ Redis queue ──▶ async workers
    ▲                  │                                     │
    │                  │                           LangGraph run graph
    └──SSE (live)──────┤                    plan ─▶ work ─▶ gate ─▶ … ─▶ finalize
                       │                      │      │       │
                       │               Supervisor  agents  interrupt() ◀── human decision
                       │                             │
                       │                       tools: RAG search · dataset queries ·
                       │                              calculator · email · Slack
                       ▼
     PostgreSQL: documents · chunks (pgvector) · datasets · workflows · runs ·
                 run_events (audit log) · approvals · outbox · evals ·
                 LangGraph checkpoints
     Redis:      job queue · pub/sub for live events
```

### Project Structure

```
hiveops/
├── backend/
│   ├── hiveops/
│   │   ├── app.py        REST API, SSE stream, serves the built UI
│   │   ├── graph.py      LangGraph orchestration: plan → work → gate → finalize
│   │   ├── agents.py     agent definitions + the tool-calling loop
│   │   ├── tools.py      tools, with approval-gated side effects
│   │   ├── rag.py        parsing, chunking, embeddings, hybrid search
│   │   ├── llm.py        Anthropic + OpenAI-compatible providers, pricing
│   │   ├── sim.py        offline simulated LLM
│   │   ├── runner.py     job queue, workers, checkpointer, run lifecycle
│   │   ├── bus.py        event log + live fan-out (Redis pub/sub)
│   │   ├── evals.py      evaluation scoring
│   │   ├── dashboard.py  command-center aggregates
│   │   ├── models.py     SQLAlchemy models (pgvector / SQLite)
│   │   └── seed_data/    demo company documents + sales CSV
│   └── tests/            51 tests
├── frontend/src/
│   ├── pages/            overview, workflows, builder, runs, run detail,
│   │                     approvals, knowledge base, data, agents, evals, settings
│   └── components/       routing map, markdown renderer, run launcher, UI kit
├── Dockerfile            one image: built UI + API
└── docker-compose.yml    app + PostgreSQL (pgvector) + Redis
```

## Quick Start

### Option 1: Docker

```bash
docker compose up --build
```

Then open http://localhost:8000. On first start the platform loads demo data for a fictional company, Northwind Analytics: four documents, a sales dataset, four workflow templates and an evaluation suite. It also runs a few workflows, two of which wait in the approval queue.

### Option 2: Local development

This uses SQLite, an in-process queue and in-memory checkpoints, so PostgreSQL and Redis are not required.

```bash
# Terminal 1: API
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn hiveops.main:app --reload

# Terminal 2: UI
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173.

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./hiveops.db` | `postgresql+asyncpg://…` enables pgvector and durable checkpoints |
| `REDIS_URL` | *(unset)* | Shared job queue and live events across processes |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | *(unset)* | Use a real LLM instead of the simulated one |
| `LLM_PROVIDER` | `auto` | Force `anthropic`, `openai` or `sim` |
| `WORKERS` | `3` | Concurrent runs per process |
| `SLACK_WEBHOOK_URL` | *(unset)* | Post approved Slack messages for real |
| `SEED_DEMO` / `SEED_DEMO_RUNS` | `true` | Load the demo data and run the demo workflows |

## Testing

```bash
cd backend && ruff check . && pytest -v          # 51 tests
cd frontend && npm run typecheck && npm test && npm run build
```

To run the backend suite against real infrastructure (CI runs both modes):

```bash
HIVEOPS_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/hiveops_test \
HIVEOPS_TEST_REDIS_URL=redis://localhost:6379/0 pytest
```

What the tests cover:

- **RAG:** retrieval returns the right document for each demo question, chunking keeps each section's heading, and embeddings are deterministic and normalised.
- **Tools:** CSV type inference, dataset aggregation, grouping and filtering, argument validation, and a calculator that blocks code injection.
- **Agents:** citations are added, side effects become pending actions instead of executing, agents cannot use tools outside their toolset, and malformed plans are handled.
- **End to end:**
  - pipeline and Supervisor runs, checking that the audit log has no gaps and the SSE stream replays and resumes correctly
  - a rejected step stops the run before later agents execute
  - an approved email is sent exactly once, and a rejected one is never sent
  - double decisions are refused, and cancellation works
  - LLM outages fail the run with the reason
  - the evaluation suite and the dashboard aggregates

## API Overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/dashboard` | KPIs, daily cost, routing map, agent health |
| GET/POST/PUT/DELETE | `/api/workflows` | Workflow builder |
| POST | `/api/workflows/{id}/run` | Delegate a task (returns 202) |
| GET | `/api/runs/{id}` | Run detail with its full event log |
| GET | `/api/runs/{id}/stream` | Live events (SSE, resumable) |
| GET / POST | `/api/approvals`, `/api/approvals/{id}/decide` | Human-in-the-loop decisions |
| GET/POST/DELETE | `/api/documents`, `/api/documents/search` | Knowledge base and retrieval |
| GET/POST/DELETE | `/api/datasets` | CSV data sources |
| GET/POST | `/api/evals/suites`, `/api/evals/runs` | Evaluations |

Interactive docs are at `/docs`.

## License

MIT
"# hiveops" 
