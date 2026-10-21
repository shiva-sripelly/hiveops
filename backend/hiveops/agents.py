"""Specialised agents and the tool-calling loop they share."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .llm import LLMError, Provider
from .tools import TOOLS, ToolContext, ToolError, execute

Emit = Callable[..., Awaitable[None]]
MAX_TURNS = 6


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    role: str
    tools: tuple[str, ...]
    color: str
    system: str


AGENTS: dict[str, AgentSpec] = {
    a.id: a
    for a in [
        AgentSpec(
            "planner",
            "Supervisor",
            "Breaks a request into steps and routes each one to the right specialist.",
            (),
            "#a78bfa",
            "You are the supervisor of a team of AI agents: researcher (knowledge base search), analyst (datasets), "
            "writer (reports), reviewer (quality checks) and communicator (email/Slack, needs approval). "
            'Reply ONLY with JSON: {"reasoning": str, "steps": [{"agent": str, "instruction": str}]}. '
            "Use the fewest steps that fully answer the request. End with writer unless the task is only a message.",
        ),
        AgentSpec(
            "researcher",
            "Research Agent",
            "Answers questions from the uploaded documents with citations (RAG).",
            ("search_documents",),
            "#22d3ee",
            "You are a research agent. Use search_documents to find evidence, then answer with short bullet points. "
            "Cite every claim as [source: <document name>]. Never invent facts that are not in the passages.",
        ),
        AgentSpec(
            "analyst",
            "Data Analyst",
            "Explores connected datasets and quantifies trends with exact numbers.",
            ("list_datasets", "describe_dataset", "query_dataset", "calculator"),
            "#34d399",
            "You are a data analyst. Inspect datasets with the tools, compute exact figures (use calculator for "
            "arithmetic) and report the key numbers as bullet points starting with '- '.",
        ),
        AgentSpec(
            "writer",
            "Report Writer",
            "Turns the team's findings into a clear, structured report.",
            (),
            "#f472b6",
            "You are a business writer. Combine the previous steps into a markdown report with: a title, "
            "'## Executive summary', '## Key findings', '## Data insights' (if data exists), '## Recommendations' "
            "and '## Sources'. Keep every number and citation exactly as given.",
        ),
        AgentSpec(
            "reviewer",
            "QA Reviewer",
            "Checks the draft for unsupported claims, missing sources and clarity.",
            (),
            "#fbbf24",
            "You are a QA reviewer. Check the draft for unsupported claims, missing citations, numbers without "
            "evidence and unclear wording. Start with 'Review verdict: PASS' or 'Review verdict: NEEDS REVISION'.",
        ),
        AgentSpec(
            "communicator",
            "Comms Agent",
            "Delivers results by email or Slack, always behind a human approval.",
            ("send_email", "post_slack_message"),
            "#fb923c",
            "You are a communications agent. Send the final report with send_email or post_slack_message, "
            "using the recipients from the task. These actions are reviewed by a human before delivery.",
        ),
    ]
}


@dataclass
class AgentResult:
    output: str
    sources: list[str] = field(default_factory=list)
    pending_actions: list[dict[str, Any]] = field(default_factory=list)


def build_prompt(task: str, instruction: str, context: str) -> str:
    parts = [f"Task: {task}", f"Your instruction: {instruction or 'Complete your part of the task.'}"]
    parts.append(f"Context from previous steps:\n{context}" if context else "Context from previous steps:\n(none)")
    return "\n\n".join(parts)


def format_context(outputs: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"### {o['agent']}\n{o['output']}" for o in outputs)


async def run_agent(
    spec: AgentSpec,
    task: str,
    instruction: str,
    context: str,
    provider: Provider,
    tool_ctx: ToolContext,
    emit: Emit,
) -> AgentResult:
    """The tool-use loop: call the model, run the tools it asks for, feed results back.

    Tools that need approval are not executed here. They are returned as
    ``pending_actions`` and the graph sends them through a human approval gate.
    """
    tools = [TOOLS[t].schema() for t in spec.tools]
    messages: list[dict[str, Any]] = [{"role": "user", "content": build_prompt(task, instruction, context)}]
    sources: list[str] = []
    pending: list[dict[str, Any]] = []

    for turn in range(MAX_TURNS):
        try:
            result = await provider.complete(spec.system, messages, tools, agent=spec.id)
        except LLMError as exc:
            await emit("agent_error", spec.id, str(exc))
            raise
        await emit(
            "llm_call",
            spec.id,
            f"{provider.model} · {result.tokens_in}→{result.tokens_out} tokens · {result.latency_ms} ms",
            {
                "tokensIn": result.tokens_in,
                "tokensOut": result.tokens_out,
                "latencyMs": result.latency_ms,
                "cost": result.cost,
                "model": result.model,
                "turn": turn,
            },
        )
        messages.append({"role": "assistant", "content": result.text, "tool_calls": result.tool_calls})
        if result.text and result.tool_calls:
            await emit("thought", spec.id, result.text)
        if not result.tool_calls:
            return AgentResult(result.text.strip(), sources, pending)

        for call in result.tool_calls:
            tool = TOOLS.get(call.name)
            if tool is None or call.name not in spec.tools:
                content = f"Error: tool {call.name!r} is not available to this agent."
                await emit("tool_error", spec.id, content, {"tool": call.name})
            elif tool.requires_approval:
                pending.append({"tool": call.name, "args": call.args, "agent": spec.id})
                content = "Submitted for human approval. It will be executed only if a reviewer approves it."
                await emit("action_proposed", spec.id, f"{call.name} needs approval", {"tool": call.name, "args": call.args})
            else:
                await emit("tool_call", spec.id, f"{call.name}({_short(call.args)})", {"tool": call.name, "args": call.args})
                try:
                    content = await execute(call.name, tool_ctx, call.args)
                    if call.name == "search_documents":
                        sources += [h["document"] for h in json.loads(content)]
                    await emit("tool_result", spec.id, _short(content, 220), {"tool": call.name, "size": len(content)})
                except ToolError as exc:
                    content = f"Error: {exc}"
                    await emit("tool_error", spec.id, content, {"tool": call.name})
            messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": content})

    await emit("agent_error", spec.id, f"Stopped after {MAX_TURNS} turns without a final answer.")
    return AgentResult(messages[-1].get("content") or "No final answer.", sources, pending)


def _short(value: Any, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"
