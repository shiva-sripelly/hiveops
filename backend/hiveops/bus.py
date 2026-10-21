"""Execution events: persisted to the database and fanned out live.

Every event is stored (the run's audit log) and published for live viewers:
via Redis pub/sub when REDIS_URL is set, so API servers and workers can be
separate processes, or in-process queues otherwise. LLM-call events also roll
token usage and cost up into the run.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import func, select, update

from .db import Database
from .models import Run, RunEvent, now

log = logging.getLogger("hiveops")
CHANNEL = "hiveops:run:{}"


class EventBus:
    def __init__(self, db: Database, redis=None):
        self.db = db
        self.redis = redis
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._local: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def emitter(self, run_id: str):
        async def emit(type_: str, agent: str | None, message: str = "", data: dict[str, Any] | None = None) -> None:
            await self.publish(run_id, type_, agent, message, data or {})

        return emit

    async def publish(self, run_id: str, type_: str, agent: str | None, message: str, data: dict[str, Any]) -> dict:
        async with self._locks[run_id]:
            async with self.db.session() as s, s.begin():
                seq = (await s.execute(select(func.coalesce(func.max(RunEvent.seq), 0)).where(RunEvent.run_id == run_id))).scalar()
                event = RunEvent(run_id=run_id, seq=seq + 1, type=type_, agent=agent, message=message[:20000], data=data, ts=now())
                s.add(event)
                if type_ == "llm_call":
                    await s.execute(
                        update(Run)
                        .where(Run.id == run_id)
                        .values(
                            tokens_in=Run.tokens_in + int(data.get("tokensIn", 0)),
                            tokens_out=Run.tokens_out + int(data.get("tokensOut", 0)),
                            cost=Run.cost + float(data.get("cost", 0.0)),
                        )
                    )
        payload = serialize_event(event)
        await self._fanout(run_id, payload)
        return payload

    async def _fanout(self, run_id: str, payload: dict) -> None:
        if self.redis is not None:
            try:
                await self.redis.publish(CHANNEL.format(run_id), json.dumps(payload))
                return
            except Exception:
                log.exception("redis publish failed; delivering locally")
        for q in list(self._local[run_id]):
            q.put_nowait(payload)

    @asynccontextmanager
    async def listen(self, run_id: str) -> AsyncIterator[AsyncIterator[dict]]:
        """Subscribe to a run's live events. The subscription is active as soon as
        the context is entered, so callers can replay stored history afterwards and
        de-duplicate by ``seq`` without missing anything in between."""
        if self.redis is not None:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe(CHANNEL.format(run_id))

            async def from_redis() -> AsyncIterator[dict]:
                while True:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                    yield json.loads(msg["data"]) if msg else {"type": "keepalive"}

            try:
                yield from_redis()
            finally:
                await pubsub.unsubscribe()
                await pubsub.aclose()
        else:
            q: asyncio.Queue = asyncio.Queue()
            self._local[run_id].add(q)

            async def from_queue() -> AsyncIterator[dict]:
                while True:
                    try:
                        yield await asyncio.wait_for(q.get(), timeout=15.0)
                    except TimeoutError:
                        yield {"type": "keepalive"}

            try:
                yield from_queue()
            finally:
                self._local[run_id].discard(q)

    async def history(self, run_id: str, after: int = 0) -> list[dict]:
        async with self.db.session() as s:
            rows = await s.execute(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after).order_by(RunEvent.seq))
            return [serialize_event(e) for e in rows.scalars()]


def serialize_event(e: RunEvent) -> dict:
    return {
        "seq": e.seq,
        "type": e.type,
        "agent": e.agent,
        "message": e.message,
        "data": e.data,
        "ts": e.ts.isoformat(),
    }
