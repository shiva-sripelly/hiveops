"""FastAPI application: REST API, live event stream (SSE) and the bundled UI."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from . import __version__, dashboard, evals, rag
from .agents import AGENTS
from .config import Settings
from .db import Database
from .models import Approval, Dataset, Document, EvalRun, EvalSuite, OutboxMessage, Run, Workflow, now
from .runner import TERMINAL, Runtime
from .seed import create_run, seed
from .tools import TOOLS, parse_csv

log = logging.getLogger("hiveops")
_background: set[asyncio.Task] = set()


# ----------------------------------------------------------------- schemas


class Step(BaseModel):
    agent: str
    instruction: str = Field(default="", max_length=1000)
    approval: bool = False

    @field_validator("agent")
    @classmethod
    def known_agent(cls, v: str) -> str:
        if v not in AGENTS or v == "planner":
            raise ValueError(f"agent must be one of {sorted(a for a in AGENTS if a != 'planner')}")
        return v


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    mode: Literal["custom", "auto"] = "custom"
    steps: list[Step] = Field(default_factory=list, max_length=12)
    default_task: str = Field(default="", max_length=4000)


class RunIn(BaseModel):
    task: str = Field(default="", max_length=4000)


class DecisionIn(BaseModel):
    approved: bool
    comment: str = Field(default="", max_length=2000)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)


def workflow_out(w: Workflow) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "description": w.description,
        "mode": w.mode,
        "steps": w.steps,
        "defaultTask": w.default_task,
        "isTemplate": w.is_template,
        "updatedAt": w.updated_at.isoformat(),
    }


# ------------------------------------------------------------------- app


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.database_url)
        await db.init()
        rt = runtime or Runtime(settings, db)
        await rt.start()
        if settings.seed_demo:
            try:
                await seed(rt)
            except Exception:
                log.exception("seeding failed")
        app.state.rt = rt
        app.state.db = db
        yield
        await rt.stop()
        await db.close()

    app = FastAPI(title="HiveOps", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    def rt(request: Request) -> Runtime:
        return request.app.state.rt

    # ------------------------------------------------------------ system

    @app.get("/api/health")
    async def health(request: Request):
        r = rt(request)
        return {
            "status": "ok",
            "version": __version__,
            "database": "postgresql" if r.db.is_postgres else "sqlite",
            "databaseOk": await r.db.ping(),
            "vectorStore": "pgvector" if r.db.is_postgres else "in-process cosine",
            "redis": await r.ping_redis(),
            "llm": {"provider": r.provider.name, "model": r.provider.model, "simulated": r.provider.simulated},
            "workers": len(r._workers),
        }

    @app.get("/api/agents")
    async def agents():
        return [
            {
                "id": a.id,
                "name": a.name,
                "role": a.role,
                "color": a.color,
                "tools": [
                    {"name": t, "requiresApproval": TOOLS[t].requires_approval, "description": TOOLS[t].description} for t in a.tools
                ],
                "system": a.system,
            }
            for a in AGENTS.values()
        ]

    @app.get("/api/dashboard")
    async def get_dashboard(request: Request, days: int = Query(14, ge=7, le=60)):
        return await dashboard.overview(rt(request).db, days)

    # --------------------------------------------------------- documents

    @app.get("/api/documents")
    async def list_documents(request: Request):
        async with rt(request).db.session() as s:
            docs = (await s.execute(select(Document).order_by(Document.created_at.desc()))).scalars().all()
        return [
            {"id": d.id, "name": d.name, "kind": d.kind, "size": d.size, "chunks": d.chunk_count, "createdAt": d.created_at.isoformat()}
            for d in docs
        ]

    @app.get("/api/documents/{doc_id}")
    async def get_document(request: Request, doc_id: str):
        async with rt(request).db.session() as s:
            d = await s.get(Document, doc_id)
        if d is None:
            raise HTTPException(404, "Document not found")
        return {"id": d.id, "name": d.name, "kind": d.kind, "size": d.size, "chunks": d.chunk_count, "preview": d.preview}

    @app.post("/api/documents", status_code=201)
    async def upload_document(request: Request, file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"Files must be under {settings.max_upload_mb} MB")
        try:
            doc = await rag.ingest(rt(request).db, file.filename or "document.txt", data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # e.g. a corrupt PDF
            raise HTTPException(400, f"Could not read this file: {exc}") from exc
        return {"id": doc.id, "name": doc.name, "chunks": doc.chunk_count}

    @app.delete("/api/documents/{doc_id}", status_code=204)
    async def remove_document(request: Request, doc_id: str):
        if not await rag.delete_document(rt(request).db, doc_id):
            raise HTTPException(404, "Document not found")

    @app.post("/api/documents/search")
    async def search_documents(request: Request, body: SearchIn):
        hits = await rag.search(rt(request).db, body.query, k=body.k)
        return [h.as_dict() for h in hits]

    # ---------------------------------------------------------- datasets

    @app.get("/api/datasets")
    async def list_datasets(request: Request):
        async with rt(request).db.session() as s:
            rows = (await s.execute(select(Dataset).order_by(Dataset.created_at.desc()))).scalars().all()
        return [
            {
                "id": d.id,
                "name": d.name,
                "source": d.source,
                "rows": d.row_count,
                "columns": d.columns,
                "createdAt": d.created_at.isoformat(),
            }
            for d in rows
        ]

    @app.get("/api/datasets/{ds_id}")
    async def get_dataset(request: Request, ds_id: str, limit: int = Query(50, ge=1, le=500)):
        async with rt(request).db.session() as s:
            d = await s.get(Dataset, ds_id)
        if d is None:
            raise HTTPException(404, "Dataset not found")
        return {"id": d.id, "name": d.name, "rows": d.row_count, "columns": d.columns, "preview": d.rows[:limit]}

    @app.post("/api/datasets", status_code=201)
    async def upload_dataset(request: Request, file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"Files must be under {settings.max_upload_mb} MB")
        if not (file.filename or "").lower().endswith(".csv"):
            raise HTTPException(400, "Upload a .csv file")
        try:
            columns, rows = parse_csv(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        name = Path(file.filename or "dataset").stem.lower().replace(" ", "_").replace("-", "_")[:60]
        try:
            async with rt(request).db.session() as s, s.begin():
                ds = Dataset(name=name, columns=columns, rows=rows, row_count=len(rows))
                s.add(ds)
        except IntegrityError as exc:
            raise HTTPException(409, f"A dataset named {name!r} already exists") from exc
        return {"id": ds.id, "name": ds.name, "rows": ds.row_count, "columns": columns}

    @app.delete("/api/datasets/{ds_id}", status_code=204)
    async def remove_dataset(request: Request, ds_id: str):
        async with rt(request).db.session() as s, s.begin():
            result = await s.execute(delete(Dataset).where(Dataset.id == ds_id))
        if not result.rowcount:
            raise HTTPException(404, "Dataset not found")

    # --------------------------------------------------------- workflows

    @app.get("/api/workflows")
    async def list_workflows(request: Request):
        async with rt(request).db.session() as s:
            rows = (await s.execute(select(Workflow).order_by(Workflow.is_template.desc(), Workflow.created_at))).scalars().all()
            counts = dict((await s.execute(select(Run.workflow_id, func.count()).group_by(Run.workflow_id))).all())
        return [{**workflow_out(w), "runCount": counts.get(w.id, 0)} for w in rows]

    @app.get("/api/workflows/{wf_id}")
    async def get_workflow(request: Request, wf_id: str):
        async with rt(request).db.session() as s:
            w = await s.get(Workflow, wf_id)
        if w is None:
            raise HTTPException(404, "Workflow not found")
        return workflow_out(w)

    def validate_workflow(body: WorkflowIn) -> None:
        if body.mode == "custom" and not body.steps:
            raise HTTPException(422, "A custom workflow needs at least one step")

    @app.post("/api/workflows", status_code=201)
    async def create_workflow(request: Request, body: WorkflowIn):
        validate_workflow(body)
        async with rt(request).db.session() as s, s.begin():
            w = Workflow(
                name=body.name,
                description=body.description,
                mode=body.mode,
                steps=[st.model_dump() for st in body.steps] if body.mode == "custom" else [],
                default_task=body.default_task,
            )
            s.add(w)
        return workflow_out(w)

    @app.put("/api/workflows/{wf_id}")
    async def update_workflow(request: Request, wf_id: str, body: WorkflowIn):
        validate_workflow(body)
        async with rt(request).db.session() as s, s.begin():
            w = await s.get(Workflow, wf_id)
            if w is None:
                raise HTTPException(404, "Workflow not found")
            w.name, w.description, w.mode, w.default_task = body.name, body.description, body.mode, body.default_task
            w.steps = [st.model_dump() for st in body.steps] if body.mode == "custom" else []
            w.updated_at = now()
        return workflow_out(w)

    @app.delete("/api/workflows/{wf_id}", status_code=204)
    async def delete_workflow(request: Request, wf_id: str):
        async with rt(request).db.session() as s, s.begin():
            result = await s.execute(delete(Workflow).where(Workflow.id == wf_id))
        if not result.rowcount:
            raise HTTPException(404, "Workflow not found")

    @app.post("/api/workflows/{wf_id}/run", status_code=202)
    async def run_workflow(request: Request, wf_id: str, body: RunIn):
        r = rt(request)
        async with r.db.session() as s:
            w = await s.get(Workflow, wf_id)
        if w is None:
            raise HTTPException(404, "Workflow not found")
        if not (body.task.strip() or w.default_task):
            raise HTTPException(422, "Describe the task for the agents")
        run = await create_run(r, w, body.task or None)
        return dashboard.run_summary(run)

    # ---------------------------------------------------------------- runs

    @app.get("/api/runs")
    async def list_runs(request: Request, status: str | None = None, limit: int = Query(50, ge=1, le=200)):
        async with rt(request).db.session() as s:
            stmt = select(Run).order_by(Run.created_at.desc()).limit(limit)
            if status:
                stmt = stmt.where(Run.status == status)
            rows = (await s.execute(stmt)).scalars().all()
        return [dashboard.run_summary(r) for r in rows]

    @app.get("/api/runs/{run_id}")
    async def get_run(request: Request, run_id: str):
        r = rt(request)
        async with r.db.session() as s:
            run = await s.get(Run, run_id)
            if run is None:
                raise HTTPException(404, "Run not found")
            approvals = (await s.execute(select(Approval).where(Approval.run_id == run_id).order_by(Approval.created_at))).scalars().all()
            outbox = (await s.execute(select(OutboxMessage).where(OutboxMessage.run_id == run_id))).scalars().all()
        return {
            **dashboard.run_summary(run),
            "steps": run.steps,
            "output": run.output,
            "sources": run.sources,
            "error": run.error,
            "provider": run.provider,
            "model": run.model,
            "tokensIn": run.tokens_in,
            "tokensOut": run.tokens_out,
            "events": await r.bus.history(run_id),
            "approvals": [dashboard.approval_summary(a) for a in approvals],
            "deliveries": [
                {"channel": o.channel, "recipient": o.recipient, "subject": o.subject, "delivered": o.delivered, "detail": o.detail}
                for o in outbox
            ],
        }

    @app.get("/api/runs/{run_id}/stream")
    async def stream_run(request: Request, run_id: str, after: int = 0):
        """Server-sent events: replays history after ``after``, then streams live until the run ends."""
        r = rt(request)
        async with r.db.session() as s:
            if await s.get(Run, run_id) is None:
                raise HTTPException(404, "Run not found")
        last_id = request.headers.get("last-event-id")
        after = int(last_id) if last_id and last_id.isdigit() else after

        async def gen():
            async with r.bus.listen(run_id) as live:  # subscribe first, then replay history
                seen = after
                for ev in await r.bus.history(run_id, after):
                    seen = ev["seq"]
                    yield f"id: {ev['seq']}\nevent: run_event\ndata: {json.dumps(ev)}\n\n"
                async with r.db.session() as s:
                    run = await s.get(Run, run_id)
                if run and run.status in TERMINAL:
                    yield "event: end\ndata: {}\n\n"
                    return
                async for ev in live:
                    if await request.is_disconnected():
                        return
                    if ev.get("type") == "keepalive":
                        yield ": keepalive\n\n"
                        continue
                    if ev["seq"] <= seen:
                        continue
                    seen = ev["seq"]
                    yield f"id: {ev['seq']}\nevent: run_event\ndata: {json.dumps(ev)}\n\n"
                    if ev["type"] == "run_finished":
                        yield "event: end\ndata: {}\n\n"
                        return

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(request: Request, run_id: str):
        r = rt(request)
        async with r.db.session() as s, s.begin():
            run = await s.get(Run, run_id)
            if run is None:
                raise HTTPException(404, "Run not found")
            if run.status not in ("queued", "awaiting_approval"):
                raise HTTPException(409, f"A {run.status} run cannot be cancelled")
            run.status, run.error, run.finished_at = "failed", "Cancelled by user", now()
            await s.execute(update(Approval).where(Approval.run_id == run_id, Approval.status == "pending").values(status="cancelled"))
        await r.bus.emitter(run_id)("run_finished", None, "Run cancelled by user", {"status": "failed"})
        return {"status": "failed"}

    # ---------------------------------------------------------- approvals

    @app.get("/api/approvals")
    async def list_approvals(request: Request, status: str | None = None, limit: int = Query(100, ge=1, le=500)):
        async with rt(request).db.session() as s:
            stmt = select(Approval, Run.workflow_name, Run.task).join(Run, Run.id == Approval.run_id)
            if status:
                stmt = stmt.where(Approval.status == status)
            rows = (await s.execute(stmt.order_by(Approval.created_at.desc()).limit(limit))).all()
        return [{**dashboard.approval_summary(a), "workflowName": wf, "task": task} for a, wf, task in rows]

    @app.post("/api/approvals/{approval_id}/decide")
    async def decide(request: Request, approval_id: str, body: DecisionIn):
        r = rt(request)
        async with r.db.session() as s, s.begin():
            a = await s.get(Approval, approval_id, with_for_update=r.db.is_postgres)
            if a is None:
                raise HTTPException(404, "Approval not found")
            if a.status != "pending":
                raise HTTPException(409, f"Already {a.status}")
            a.status = "approved" if body.approved else "rejected"
            a.comment = body.comment
            a.decided_at = now()
            await s.execute(update(Run).where(Run.id == a.run_id).values(status="queued"))
        await r.bus.emitter(a.run_id)(
            "approval_decided",
            a.agent,
            f"{a.status.capitalize()} by reviewer" + (f": {body.comment}" if body.comment else ""),
            {"approvalId": a.id, "approved": body.approved},
        )
        await r.enqueue_resume(a.run_id, {"approved": body.approved, "comment": body.comment})
        return dashboard.approval_summary(a)

    # -------------------------------------------------------- integrations

    @app.get("/api/outbox")
    async def outbox(request: Request, limit: int = Query(50, ge=1, le=200)):
        async with rt(request).db.session() as s:
            rows = (await s.execute(select(OutboxMessage).order_by(OutboxMessage.created_at.desc()).limit(limit))).scalars().all()
        return [
            {
                "id": o.id,
                "runId": o.run_id,
                "channel": o.channel,
                "recipient": o.recipient,
                "subject": o.subject,
                "body": o.body,
                "delivered": o.delivered,
                "detail": o.detail,
                "createdAt": o.created_at.isoformat(),
            }
            for o in rows
        ]

    # --------------------------------------------------------------- evals

    @app.get("/api/evals/suites")
    async def eval_suites(request: Request):
        async with rt(request).db.session() as s:
            suites = (await s.execute(select(EvalSuite).order_by(EvalSuite.created_at))).scalars().all()
        return [{"id": e.id, "name": e.name, "description": e.description, "cases": e.cases} for e in suites]

    @app.post("/api/evals/suites/{suite_id}/run", status_code=202)
    async def run_eval(request: Request, suite_id: str):
        r = rt(request)
        async with r.db.session() as s, s.begin():
            suite = await s.get(EvalSuite, suite_id)
            if suite is None:
                raise HTTPException(404, "Eval suite not found")
            er = EvalRun(suite_id=suite_id, provider=r.provider.name, model=r.provider.model)
            s.add(er)
        task = asyncio.create_task(evals.run_suite(r, suite, er.id))
        _background.add(task)  # keep a reference so the task is not garbage-collected
        task.add_done_callback(_background.discard)
        return {"id": er.id, "status": er.status}

    @app.get("/api/evals/runs")
    async def eval_runs(request: Request, limit: int = Query(20, ge=1, le=100)):
        async with rt(request).db.session() as s:
            rows = (
                await s.execute(
                    select(EvalRun, EvalSuite.name)
                    .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
                    .order_by(EvalRun.created_at.desc())
                    .limit(limit)
                )
            ).all()
        return [
            {
                "id": e.id,
                "suiteId": e.suite_id,
                "suiteName": name,
                "status": e.status,
                "provider": e.provider,
                "model": e.model,
                "metrics": e.metrics,
                "results": e.results,
                "createdAt": e.created_at.isoformat(),
            }
            for e, name in rows
        ]

    # ---------------------------------------------------------- frontend

    static = Path(settings.static_dir) if settings.static_dir else None
    if static and static.is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            target = static / path
            if path and target.is_file() and static in target.resolve().parents:
                return FileResponse(target)
            return FileResponse(static / "index.html")  # client-side routing

    return app
