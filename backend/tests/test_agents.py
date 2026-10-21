import asyncio

from sqlalchemy import func, select

from hiveops import evals, rag
from hiveops.agents import AGENTS, run_agent
from hiveops.config import Settings
from hiveops.db import Database
from hiveops.graph import parse_plan
from hiveops.llm import LLMResult, ToolCall, price
from hiveops.models import OutboxMessage
from hiveops.seed import DATA
from hiveops.sim import SimProvider
from hiveops.tools import ToolContext


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, type_, agent, message="", data=None):
        self.events.append((type_, agent, message, data or {}))


def setup_db(tmp_path) -> Database:
    async def go():
        db = Database(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
        await db.init()
        for path in sorted(DATA.glob("*.md")):
            await rag.ingest(db, path.name, path.read_bytes())
        return db

    return asyncio.run(go())


def test_researcher_searches_and_cites_sources(tmp_path):
    db = setup_db(tmp_path)
    rec = Recorder()
    result = asyncio.run(
        run_agent(AGENTS["researcher"], "What is the hotel limit in London?", "", "", SimProvider(0), ToolContext(db, Settings()), rec)
    )
    assert "$350" in result.output and "[source: employee_handbook.md]" in result.output
    assert "employee_handbook.md" in result.sources
    types = [e[0] for e in rec.events]
    assert types.count("llm_call") == 2 and "tool_call" in types and "tool_result" in types


def test_side_effects_become_pending_actions_not_executions(tmp_path):
    db = setup_db(tmp_path)
    rec = Recorder()
    result = asyncio.run(
        run_agent(AGENTS["communicator"], "Email the summary to cfo@northwind.example", "", "### writer\n# Report", SimProvider(0), ToolContext(db, Settings()), rec)
    )
    assert result.pending_actions == [
        {"tool": "send_email", "args": result.pending_actions[0]["args"], "agent": "communicator"}
    ]
    assert result.pending_actions[0]["args"]["to"] == "cfo@northwind.example"

    async def outbox_count():
        async with db.session() as s:
            return (await s.execute(select(func.count()).select_from(OutboxMessage))).scalar()

    assert asyncio.run(outbox_count()) == 0  # nothing was sent without approval


class ScriptedProvider:
    """Asks for a tool the agent is not allowed to use, then answers."""

    name, model, simulated = "scripted", "scripted-1", False

    def __init__(self):
        self.calls = 0

    async def complete(self, system, messages, tools, agent=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResult("", [ToolCall("send_email", {"to": "x@y.z"})], 10, 5, 1, self.model)
        return LLMResult("Done without sending.", [], 10, 5, 1, self.model)


def test_agents_cannot_use_tools_outside_their_toolset(tmp_path):
    db = setup_db(tmp_path)
    rec = Recorder()
    result = asyncio.run(run_agent(AGENTS["researcher"], "task", "", "", ScriptedProvider(), ToolContext(db, Settings()), rec))
    assert result.output == "Done without sending." and not result.pending_actions
    assert any(e[0] == "tool_error" for e in rec.events)


def test_parse_plan_is_robust():
    fenced = '```json\n{"steps": [{"agent": "analyst", "instruction": "x"}, {"agent": "hacker"}, {"agent": "Writer"}]}\n```'
    assert [s["agent"] for s in parse_plan(fenced)] == ["analyst", "writer"]
    assert [s["agent"] for s in parse_plan("I think we should research first.")] == ["researcher", "writer"]
    assert parse_plan('{"steps": [{"agent": "planner"}]}')[0]["agent"] == "researcher"  # supervisor cannot route to itself


def test_simulated_planner_routes_by_intent():
    async def plan(task):
        result = await SimProvider(0).complete("", [{"role": "user", "content": f"Task: {task}\n\nYour instruction: plan"}], [], agent="planner")
        return [s["agent"] for s in parse_plan(result.text)]

    assert asyncio.run(plan("What is our travel policy?")) == ["researcher", "writer"]
    assert "analyst" in asyncio.run(plan("Show revenue by region for 2026"))
    assert asyncio.run(plan("Summarize the contract risks and email legal@x.example"))[-1] == "communicator"


def test_pricing():
    assert price("claude-haiku-5-5", 1_000_000, 0) == 1.0
    assert price("gpt-4o-mini", 0, 1_000_000) == 0.6
    assert price("unknown-model", 10_000, 10_000) == 0.0


def test_eval_scoring_functions():
    assert evals.recall("The cap is 12 months of fees", ["12 months"]) == 1.0
    assert evals.recall("No idea", ["12 months", "fees"]) == 0.0
    passages = ["The hotel limit is $250 per night in most cities and $350 per night in London."]
    assert evals.groundedness("- The hotel limit is $350 per night in London. [source: h.md]", passages) == 1.0
    assert evals.groundedness("- Employees receive free unlimited helicopter rides every weekend.", passages) == 0.0
