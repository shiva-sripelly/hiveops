"""Multi-agent orchestration with LangGraph.

One graph serves both workflow modes:

* ``auto``: a Supervisor agent plans the steps and routes them to specialists.
* ``custom``: steps come from the workflow builder.

    plan ──▶ work ──▶ (gate) ──▶ work ──▶ … ──▶ finalize
                 ▲        │
                 └────────┘   gate = human approval via interrupt()

Human approvals use LangGraph's ``interrupt()``. The graph pauses, its state
is checkpointed (PostgreSQL in production), and it resumes when a reviewer
decides, possibly in a different worker process. Each gate node raises at most
one interrupt and only performs its side effect after the decision, so
approved actions execute exactly once.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from .agents import AGENTS, format_context, run_agent
from .tools import ToolContext, ToolError, execute

VALID_AGENTS = {a for a in AGENTS if a != "planner"}


class RunState(TypedDict, total=False):
    task: str
    mode: str
    plan: list[dict[str, Any]]  # [{agent, instruction, approval}]
    idx: int
    outputs: list[dict[str, Any]]  # [{agent, output, sources}]
    gates: list[dict[str, Any]]  # approvals still to ask for after the current step
    status: str  # running | rejected | completed
    final: str
    sources: list[str]


def _deps(config: RunnableConfig):
    from .runner import runtime  # the process-wide services (db, provider, event bus)

    run_id = config["configurable"]["thread_id"]
    return runtime(), run_id


def parse_plan(text: str) -> list[dict[str, Any]]:
    """Extract and validate the supervisor's JSON plan (tolerates code fences and prose)."""
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    steps = []
    for s in data.get("steps", []) if isinstance(data, dict) else []:
        agent = str(s.get("agent", "")).lower()
        if agent in VALID_AGENTS:
            steps.append({"agent": agent, "instruction": str(s.get("instruction", ""))[:500], "approval": False})
    if not steps:  # never fail a run because the plan was malformed
        steps = [{"agent": "researcher", "instruction": "", "approval": False}, {"agent": "writer", "instruction": "", "approval": False}]
    return steps[:8]


async def plan_node(state: RunState, config: RunnableConfig) -> RunState:
    rt, run_id = _deps(config)
    emit = rt.bus.emitter(run_id)
    if state["mode"] != "auto":
        await emit("plan", "planner", "Running the workflow as designed", {"steps": state["plan"]})
        return {"idx": 0, "outputs": [], "gates": [], "status": "running"}

    await emit("agent_start", "planner", "Supervisor is planning the work")
    spec = AGENTS["planner"]
    result = await run_agent(spec, state["task"], "Plan the work.", "", rt.provider, rt.tool_ctx(run_id), emit)
    plan = parse_plan(result.output)
    reasoning = ""
    try:
        reasoning = json.loads(re.search(r"\{.*\}", result.output, re.S).group(0)).get("reasoning", "")
    except (AttributeError, json.JSONDecodeError):
        pass
    await emit("plan", "planner", reasoning or "Plan ready", {"steps": plan})
    return {"plan": plan, "idx": 0, "outputs": [], "gates": [], "status": "running"}


async def work_node(state: RunState, config: RunnableConfig) -> RunState:
    rt, run_id = _deps(config)
    emit = rt.bus.emitter(run_id)
    step = state["plan"][state["idx"]]
    spec = AGENTS[step["agent"]]
    await emit("agent_start", spec.id, f"{spec.name}: {step.get('instruction') or spec.role}", {"step": state["idx"]})
    result = await run_agent(
        spec, state["task"], step.get("instruction", ""), format_context(state["outputs"]), rt.provider, rt.tool_ctx(run_id), emit
    )
    await emit("agent_output", spec.id, result.output, {"step": state["idx"], "sources": sorted(set(result.sources))})

    gates = [{"kind": "tool_action", **a} for a in result.pending_actions]
    if step.get("approval"):
        gates.append({"kind": "step_output", "agent": spec.id, "output": result.output})
    outputs = [*state["outputs"], {"agent": spec.id, "output": result.output, "sources": sorted(set(result.sources))}]
    return {"outputs": outputs, "gates": gates, "idx": state["idx"] + 1}


async def gate_node(state: RunState, config: RunnableConfig) -> RunState:
    """Ask a human about the first pending gate. One interrupt per execution."""
    rt, run_id = _deps(config)
    emit = rt.bus.emitter(run_id)
    gate, rest = state["gates"][0], state["gates"][1:]
    decision = interrupt(gate)  # pauses the graph here until a reviewer decides
    approved = bool(decision.get("approved"))
    comment = str(decision.get("comment", ""))

    if gate["kind"] == "step_output":
        if not approved:
            await emit("rejected", gate["agent"], f"Output rejected by reviewer. {comment}".strip())
            return {"gates": [], "status": "rejected"}
        await emit("approved", gate["agent"], f"Output approved. {comment}".strip())
        return {"gates": rest}

    # A tool action (email, Slack…): execute only after approval.
    tool, args = gate["tool"], gate["args"]
    if not approved:
        await emit("rejected", gate["agent"], f"{tool} was rejected and not executed. {comment}".strip(), {"tool": tool})
        note = f"[{tool} rejected by reviewer: {comment or 'no comment'}]"
    else:
        await emit("approved", gate["agent"], f"{tool} approved. {comment}".strip(), {"tool": tool})
        try:
            result = await execute(tool, rt.tool_ctx(run_id), args)
            await emit("tool_result", gate["agent"], result, {"tool": tool})
            note = f"[{tool} executed: {result}]"
        except ToolError as exc:
            await emit("tool_error", gate["agent"], str(exc), {"tool": tool})
            note = f"[{tool} failed: {exc}]"
    outputs = list(state["outputs"])
    last = dict(outputs[-1])
    last["output"] = f"{last['output']}\n\n{note}"
    outputs[-1] = last
    return {"gates": rest, "outputs": outputs}


async def finalize_node(state: RunState, config: RunnableConfig) -> RunState:
    rt, run_id = _deps(config)
    outputs = state["outputs"]
    final = next((o["output"] for o in reversed(outputs) if o["agent"] == "writer"), outputs[-1]["output"] if outputs else "")
    if outputs and outputs[-1]["agent"] == "communicator" and final != outputs[-1]["output"]:
        final = f"{final}\n\n---\n{outputs[-1]['output']}"
    sources = sorted({s for o in outputs for s in o.get("sources", [])})
    await rt.bus.emitter(run_id)("run_completed", None, "Workflow completed", {"sources": sources})
    return {"final": final, "sources": sources, "status": "completed"}


def _after_work(state: RunState) -> str:
    if state.get("gates"):
        return "gate"
    return "work" if state["idx"] < len(state["plan"]) else "finalize"


def _after_gate(state: RunState) -> str:
    if state.get("status") == "rejected":
        return END
    if state.get("gates"):
        return "gate"
    return "work" if state["idx"] < len(state["plan"]) else "finalize"


def build_graph(checkpointer):
    g = StateGraph(RunState)
    g.add_node("plan", plan_node)
    g.add_node("work", work_node)
    g.add_node("gate", gate_node)
    g.add_node("finalize", finalize_node)
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", lambda s: "work" if s["plan"] else "finalize", ["work", "finalize"])
    g.add_conditional_edges("work", _after_work, ["gate", "work", "finalize"])
    g.add_conditional_edges("gate", _after_gate, ["gate", "work", "finalize", END])
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def tool_ctx_factory(db, settings):
    return lambda run_id: ToolContext(db=db, settings=settings, run_id=run_id)
