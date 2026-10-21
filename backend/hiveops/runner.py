"""Run execution: a job queue, async workers, and the shared runtime.

Jobs ("start" or "resume") go on a Redis list when REDIS_URL is set, so any
number of API servers and workers can share the work; otherwise they go on an
in-process asyncio queue. Graph state is checkpointed in PostgreSQL
(AsyncPostgresSaver) or in memory for local SQLite development.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import select, update

from .bus import EventBus
from .config import Settings
from .db import Database
from .graph import build_graph, tool_ctx_factory
from .llm import LLMError, Provider, create_provider
from .models import Approval, Run, now

log = logging.getLogger("hiveops")
QUEUE_KEY = "hiveops:jobs"
TERMINAL = {"completed", "failed", "rejected"}

_runtime: Runtime | None = None


def runtime() -> Runtime:
    if _runtime is None:
        raise RuntimeError("Runtime not started")
    return _runtime


class JobQueue:
    def __init__(self, redis=None):
        self.redis = redis
        self.local: asyncio.Queue = asyncio.Queue()

    async def put(self, job: dict[str, Any]) -> None:
        if self.redis is not None:
            await self.redis.lpush(QUEUE_KEY, json.dumps(job))
        else:
            await self.local.put(job)

    async def get(self) -> dict[str, Any]:
        if self.redis is not None:
            from redis.exceptions import TimeoutError as RedisTimeout

            while True:
                try:
                    item = await self.redis.brpop([QUEUE_KEY], timeout=5)
                except RedisTimeout:
                    continue  # no job within the block window; poll again
                if item:
                    return json.loads(item[1])
        return await self.local.get()


class Runtime:
    def __init__(self, settings: Settings, db: Database, provider: Provider | None = None):
        self.settings = settings
        self.db = db
        self.provider = provider or create_provider(settings)
        self.redis = None
        queue_redis = None
        if settings.redis_url:
            import redis.asyncio as redis

            self.redis = redis.from_url(settings.redis_url, decode_responses=True)
            # Blocking pops get their own connection pool, with a read timeout longer than the block window.
            queue_redis = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=15)
        self.bus = EventBus(db, self.redis)
        self.queue = JobQueue(queue_redis)
        self.tool_ctx = tool_ctx_factory(db, settings)
        self._stack = contextlib.AsyncExitStack()
        self._workers: list[asyncio.Task] = []
        self.graph = None

    async def start(self, workers: int | None = None) -> None:
        global _runtime
        if self.db.is_postgres:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            conn = self.settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
            saver = await self._stack.enter_async_context(AsyncPostgresSaver.from_conn_string(conn))
            await saver.setup()
        else:
            saver = InMemorySaver()
        self.graph = build_graph(saver)
        _runtime = self
        await self._recover()
        for i in range(self.settings.workers if workers is None else workers):
            self._workers.append(asyncio.create_task(self._worker(i)))

    async def stop(self) -> None:
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        await self._stack.aclose()
        if self.redis is not None:
            await self.redis.aclose()
        if self.queue.redis is not None:
            await self.queue.redis.aclose()

    async def ping_redis(self) -> bool | None:
        if self.redis is None:
            return None
        try:
            return bool(await self.redis.ping())
        except Exception:
            return False

    async def _recover(self) -> None:
        """Runs that were mid-execution when the process stopped are marked failed
        (their partial side effects are in the event log); queued runs are re-queued."""
        async with self.db.session() as s, s.begin():
            await s.execute(
                update(Run)
                .where(Run.status == "running")
                .values(status="failed", error="Interrupted by a server restart", finished_at=now())
            )
            queued = (await s.execute(select(Run.id).where(Run.status == "queued"))).scalars().all()
        if self.redis is None:
            for run_id in queued:
                await self.queue.put({"type": "start", "run_id": run_id})

    # ----------------------------------------------------------------- API

    async def enqueue_run(self, run_id: str) -> None:
        await self.queue.put({"type": "start", "run_id": run_id})

    async def enqueue_resume(self, run_id: str, decision: dict[str, Any]) -> None:
        await self.queue.put({"type": "resume", "run_id": run_id, "decision": decision})

    # -------------------------------------------------------------- worker

    async def _worker(self, n: int) -> None:
        while True:
            try:
                job = await self.queue.get()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("queue error")
                await asyncio.sleep(1)
                continue
            try:
                await self.execute(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job failed: %s", job)

    async def execute(self, job: dict[str, Any]) -> None:
        run_id = job["run_id"]
        async with self.db.session() as s:
            run = await s.get(Run, run_id)
        if run is None or run.status in TERMINAL:
            return
        emit = self.bus.emitter(run_id)
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 60}

        await self._set(run_id, status="running")
        started = time.perf_counter()
        try:
            if job["type"] == "start":
                await emit("run_started", None, f"Run started: {run.workflow_name}", {"mode": run.mode, "provider": self.provider.name})
                state = {"task": run.task, "mode": run.mode, "plan": run.steps}
                result = await self.graph.ainvoke(state, config)
            else:
                result = await self.graph.ainvoke(Command(resume=job["decision"]), config)
        except LLMError as exc:
            await self._fail(run_id, str(exc), started)
            return
        except Exception as exc:
            log.exception("run %s crashed", run_id)
            await self._fail(run_id, f"{type(exc).__name__}: {exc}", started)
            return

        elapsed = int((time.perf_counter() - started) * 1000)
        plan = [o["agent"] for o in result.get("outputs", [])]  # agents that actually ran, in order
        interrupts = result.get("__interrupt__") or []
        if interrupts:
            gate = interrupts[0].value
            await self._open_approval(run_id, gate, emit)
            await self._set(run_id, status="awaiting_approval", plan=plan, add_ms=elapsed)
            return

        status = result.get("status", "completed")
        if status == "rejected":
            await self._set(
                run_id,
                status="rejected",
                plan=plan,
                add_ms=elapsed,
                finished=True,
                output=result.get("outputs", [{}])[-1].get("output", "") if result.get("outputs") else "",
            )
            await emit("run_finished", None, "Run stopped: output rejected by a reviewer", {"status": "rejected"})
            return
        await self._set(
            run_id,
            status="completed",
            plan=plan,
            add_ms=elapsed,
            finished=True,
            output=result.get("final", ""),
            sources=result.get("sources", []),
        )
        await emit("run_finished", None, "Run completed", {"status": "completed"})

    async def _open_approval(self, run_id: str, gate: dict[str, Any], emit) -> None:
        if gate["kind"] == "tool_action":
            args = gate["args"]
            target = args.get("to") or args.get("channel") or ""
            title = f"{gate['tool'].replace('_', ' ').capitalize()} → {target}".strip()
        else:
            title = f"Review {gate['agent']} output before continuing"
        async with self.db.session() as s, s.begin():
            approval = Approval(run_id=run_id, kind=gate["kind"], agent=gate["agent"], title=title[:255], payload=gate)
            s.add(approval)
        await emit("approval_requested", gate["agent"], title, {"approvalId": approval.id, "kind": gate["kind"]})

    async def _fail(self, run_id: str, error: str, started: float) -> None:
        await self._set(run_id, status="failed", error=error[:2000], finished=True, add_ms=int((time.perf_counter() - started) * 1000))
        await self.bus.emitter(run_id)("run_finished", None, f"Run failed: {error}", {"status": "failed"})

    async def _set(self, run_id: str, *, add_ms: int = 0, finished: bool = False, **values: Any) -> None:
        if finished:
            values["finished_at"] = now()
        async with self.db.session() as s, s.begin():
            stmt = update(Run).where(Run.id == run_id).values(**values)
            if add_ms:
                stmt = stmt.values(active_ms=Run.active_ms + add_ms)
            await s.execute(stmt)
