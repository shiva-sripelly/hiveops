"""Test fixtures.

By default tests use SQLite, the in-process queue and the simulated LLM. Set
HIVEOPS_TEST_DATABASE_URL (PostgreSQL with pgvector) and HIVEOPS_TEST_REDIS_URL
to run the same suite against real infrastructure. CI does both.
"""

import asyncio
import os
import time

import pytest
from fastapi.testclient import TestClient

from hiveops.app import create_app
from hiveops.config import Settings

PG_URL = os.environ.get("HIVEOPS_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("HIVEOPS_TEST_REDIS_URL")


async def _reset_postgres(url: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from hiveops.models import Base

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _reset_redis(url: str) -> None:
    import redis.asyncio as redis

    r = redis.from_url(url)
    await r.flushdb()
    await r.aclose()


@pytest.fixture
def settings(tmp_path) -> Settings:
    if PG_URL:
        asyncio.run(_reset_postgres(PG_URL))
    if REDIS_URL:
        asyncio.run(_reset_redis(REDIS_URL))
    return Settings(
        database_url=PG_URL or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        redis_url=REDIS_URL,
        llm_provider="sim",
        sim_delay=0,
        workers=2,
        seed_demo=True,
        seed_demo_runs=False,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def wait_for(client, run_id: str, statuses: set[str], timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} stuck in {run['status']}")


def workflow_id(client, name: str) -> str:
    return next(w["id"] for w in client.get("/api/workflows").json() if w["name"] == name)
