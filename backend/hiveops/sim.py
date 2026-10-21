"""A deterministic, offline stand-in for an LLM.

It lets the whole platform run, demo and be tested with no API key. It follows
the same contract as a real model: it reads the conversation, chooses tools,
reads tool results and writes an answer. Its "reasoning" is rule-based
(keyword planning, extractive summaries, templated reports), so outputs are
reproducible. Set ANTHROPIC_API_KEY or OPENAI_API_KEY to use a real model.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from .llm import LLMResult, ToolCall
from .rag import keyword_overlap, tokens

MODEL = "hive-sim-1"
DATA_WORDS = {
    "revenue",
    "sale",
    "data",
    "dataset",
    "csv",
    "number",
    "metric",
    "trend",
    "region",
    "quarter",
    "total",
    "average",
    "growth",
    "unit",
    "product",
    "kpi",
    "forecast",
    "performance",
    "month",
}
DOC_WORDS = {
    "policy",
    "policie",
    "document",
    "handbook",
    "faq",
    "contract",
    "term",
    "report",
    "according",
    "explain",
    "summarize",
    "summary",
    "research",
    "risk",
    "plan",
    "pricing",
    "sla",
    "expense",
    "q3",
    "priority",
    "prioritie",
}
SEND_WORDS = {"email", "send", "notify", "share", "slack", "post", "message", "distribute"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _section(text: str, label: str) -> str:
    m = re.search(rf"{label}:\s*(.*?)(?:\n\n[A-Z][\w ]+:|\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def _context(prompt: str) -> str:
    """Everything after the 'Context from previous steps:' marker (always last in the prompt)."""
    return prompt.split("Context from previous steps:", 1)[1] if "Context from previous steps:" in prompt else ""


def _context_blocks(text: str) -> dict[str, str]:
    """Previous agents' outputs, passed as '### <agent>' blocks."""
    blocks: dict[str, str] = {}
    for m in re.finditer(r"^### (\w+)\n(.*?)(?=^### \w+\n|\Z)", text, re.S | re.M):
        blocks[m.group(1)] = m.group(2).strip()
    return blocks


def _sentences(text: str) -> list[str]:
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -*•") for p in parts if len(p.strip()) > 25]


def _title(task: str, limit: int = 72) -> str:
    title = re.sub(r"\s+", " ", re.split(r"(?<=[.!?])\s", task.strip())[0]).rstrip(".!? ")
    if len(title) > limit:
        title = title[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return title[:1].upper() + title[1:] if title else "Report"


def _fmt(n: float) -> str:
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs(n) >= 10_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,.0f}" if float(n).is_integer() else f"{n:,.2f}"


class SimProvider:
    name = "sim"
    simulated = True
    model = MODEL

    def __init__(self, delay: float = 0.25):
        self.delay = delay

    async def complete(self, system, messages, tools, agent=None) -> LLMResult:
        started = time.perf_counter()
        prompt = messages[0]["content"] if messages else ""
        history = self._tool_history(messages)
        handler = getattr(self, f"_{agent}", None) if agent else None
        text, calls = handler(prompt, history) if handler else ("Done.", [])
        if self.delay:
            await asyncio.sleep(self.delay * (0.6 + (len(prompt) % 7) / 10))
        size_in = len(system) + sum(len(str(m.get("content", ""))) for m in messages)
        size_out = len(text) + sum(len(json.dumps(c.args)) for c in calls)
        return LLMResult(text, calls, max(1, size_in // 4), max(1, size_out // 4), int((time.perf_counter() - started) * 1000), MODEL)

    @staticmethod
    def _tool_history(messages: list[dict[str, Any]]) -> list[tuple[str, dict, str]]:
        calls: dict[str, tuple[str, dict]] = {}
        out = []
        for m in messages:
            for tc in m.get("tool_calls") or []:
                calls[tc.id] = (tc.name, tc.args)
            if m["role"] == "tool" and m["tool_call_id"] in calls:
                name, args = calls[m["tool_call_id"]]
                out.append((name, args, m["content"]))
        return out

    # ------------------------------------------------------------ agents

    def _planner(self, prompt: str, history) -> tuple[str, list[ToolCall]]:
        task = _section(prompt, "Task") or prompt
        words = set(tokens(task))
        steps = []
        if words & DOC_WORDS or not words & DATA_WORDS:
            steps.append({"agent": "researcher", "instruction": "Find the relevant facts in the knowledge base and cite sources."})
        if words & DATA_WORDS:
            steps.append({"agent": "analyst", "instruction": "Analyse the connected datasets and quantify the key numbers."})
        steps.append({"agent": "writer", "instruction": "Combine the findings into a concise, well-structured report."})
        if words & {"review", "verify", "check", "audit", "risk"}:
            steps.append({"agent": "reviewer", "instruction": "Check the report for unsupported claims and missing sources."})
        if words & SEND_WORDS:
            steps.append({"agent": "communicator", "instruction": "Send the final report to the requested recipients."})
        reason = "Routed by intent: " + ", ".join(s["agent"] for s in steps)
        return json.dumps({"reasoning": reason, "steps": steps}), []

    def _researcher(self, prompt: str, history) -> tuple[str, list[ToolCall]]:
        task = _section(prompt, "Task")
        instruction = _section(prompt, "Your instruction")
        searches = [h for h in history if h[0] == "search_documents"]
        if not searches:
            query = f"{task} {instruction}".strip()
            return "Searching the knowledge base.", [ToolCall("search_documents", {"query": query[:300], "k": 5})]
        try:
            hits = json.loads(searches[-1][2])
        except json.JSONDecodeError:
            hits = []
        return self._synthesize(f"{task} {instruction}", hits), []

    def _rag(self, prompt: str, history) -> tuple[str, list[ToolCall]]:
        question = _section(prompt, "Question")
        hits = [
            {"document": m.group(1), "text": m.group(2)} for m in re.finditer(r"\[source: (.+?)\]\n(.*?)(?=\n\[source: |\Z)", prompt, re.S)
        ]
        return self._synthesize(question, hits, max_points=3), []

    @staticmethod
    def _synthesize(query: str, hits: list[dict], max_points: int = 5) -> str:
        scored = []
        for rank, hit in enumerate(hits):
            for sentence in _sentences(hit.get("text", "")):
                overlap = keyword_overlap(query, sentence)
                if overlap > 0:
                    scored.append((overlap - rank * 0.02, sentence, hit.get("document", "?")))
        scored.sort(key=lambda x: x[0], reverse=True)
        seen: set[str] = set()
        points = []
        for _, sentence, doc in scored:
            if sentence in seen:
                continue
            seen.add(sentence)
            points.append(f"- {sentence} [source: {doc}]")
            if len(points) == max_points:
                break
        if not points:
            return "I could not find information about this in the knowledge base."
        return "Findings from the knowledge base:\n" + "\n".join(points)

    def _analyst(self, prompt: str, history) -> tuple[str, list[ToolCall]]:
        task = _section(prompt, "Task") + " " + _section(prompt, "Your instruction")
        done = [h[0] for h in history]
        if "list_datasets" not in done:
            return "Checking which datasets are connected.", [ToolCall("list_datasets", {})]
        datasets = json.loads(history[0][2]) if history else []
        if not datasets:
            return "No datasets are connected, so there is nothing to analyse.", []
        if "describe_dataset" not in done:
            target = max(datasets, key=lambda d: keyword_overlap(task, d["name"].replace("_", " ")))
            return f"Inspecting {target['name']}.", [ToolCall("describe_dataset", {"dataset": target["name"]})]

        schema = json.loads(next(h[2] for h in history if h[0] == "describe_dataset"))
        name = schema["name"]
        numeric = [c["name"] for c in schema["columns"] if c["type"] == "number"]
        text_cols = [c["name"] for c in schema["columns"] if c["type"] == "string"]
        if not numeric:
            return f"{name} has no numeric columns to analyse.", []
        metric = next((c for c in numeric for k in ("revenue", "amount", "sales", "total", "value") if k in c.lower()), numeric[0])
        task_words = set(tokens(task))
        time_col = next((c for c in text_cols if c.lower() in {"month", "date", "period", "quarter"}), None)
        group = (
            next((c for c in text_cols if c.lower() in task_words and c != time_col), None)
            or next((c for c in text_cols if c.lower() in {"region", "category", "product", "segment"}), None)
            or (text_cols[0] if text_cols else None)
        )

        queries = [h for h in history if h[0] == "query_dataset"]
        if not queries:
            return f"Aggregating {metric} by {group}.", [
                ToolCall("query_dataset", {"dataset": name, "metric": metric, "agg": "sum", "group_by": group})
            ]
        if len(queries) == 1 and time_col and time_col != group:
            return f"Checking the trend of {metric} by {time_col}.", [
                ToolCall("query_dataset", {"dataset": name, "metric": metric, "agg": "sum", "group_by": time_col, "sort": "key"})
            ]

        by_group = json.loads(queries[0][2])["rows"]
        total = sum(r["value"] for r in by_group)
        lines = [f"Analysis of `{name}` ({schema['rowCount']} rows), metric: total {metric}."]
        lines.append(f"- Total {metric}: {_fmt(total)}")
        if by_group:
            top, bottom = by_group[0], by_group[-1]
            lines.append(f"- Highest {group}: {top['key']} with {_fmt(top['value'])} ({top['value'] / total:.0%} of total)")
            lines.append(f"- Lowest {group}: {bottom['key']} with {_fmt(bottom['value'])} ({bottom['value'] / total:.0%} of total)")
            lines.append(f"- {metric.capitalize()} by {group}: " + ", ".join(f"{r['key']} {_fmt(r['value'])}" for r in by_group))
        if len(queries) > 1:
            trend = json.loads(queries[1][2])["rows"]
            if len(trend) >= 2 and trend[0]["value"]:
                first, last = trend[0], trend[-1]
                change = (last["value"] - first["value"]) / first["value"]
                lines.append(
                    f"- Trend: {metric} moved from {_fmt(first['value'])} in {first['key']} to "
                    f"{_fmt(last['value'])} in {last['key']} ({change:+.0%})"
                )
        return "\n".join(lines), []

    def _writer(self, prompt: str, history) -> tuple[str, list[ToolCall]]:
        task = _section(prompt, "Task")
        blocks = _context_blocks(_context(prompt))
        research = [ln for ln in blocks.get("researcher", "").splitlines() if ln.startswith("- ")]
        data = [ln for ln in blocks.get("analyst", "").splitlines() if ln.startswith("- ")]
        sources = sorted({m for ln in research for m in re.findall(r"\[source: (.+?)\]", ln)})
        title = _title(task)

        out = [f"# {title}", ""]
        summary = []
        if research:
            summary.append(re.sub(r"\s*\[source: .+?\]", "", research[0][2:]))
        if data:
            line = data[1][2:] if len(data) > 1 else data[0][2:]
            summary.append(line if line.endswith(".") else line + ".")
        out += ["## Executive summary", " ".join(summary) or "No supporting information was found for this request.", ""]
        if research:
            out += ["## Key findings", *research, ""]
        if data:
            out += ["## Data insights", *data, ""]
        recs = []
        top = next((ln for ln in data if ln.startswith("- Highest")), None)
        low = next((ln for ln in data if ln.startswith("- Lowest")), None)
        if top:
            recs.append(f"Double down on what is working: {top[2:].split(' with ')[0].replace('Highest ', 'the strongest ')}.")
        if low:
            recs.append(f"Investigate under-performance in {low[2:].split(' with ')[0].replace('Lowest ', 'the weakest ')}.")
        if research:
            recs.append("Share these findings with the owners named in the source documents and confirm next steps.")
        if recs:
            out += ["## Recommendations", *[f"{i}. {r}" for i, r in enumerate(recs, 1)], ""]
        if sources:
            out += ["## Sources", *[f"- {s}" for s in sources]]
        return "\n".join(out).strip(), []

    def _reviewer(self, prompt: str, history) -> tuple[str, list[ToolCall]]:
        blocks = _context_blocks(_context(prompt))
        draft = blocks.get("writer") or "\n".join(blocks.values())
        checks = [
            ("Claims cite sources", "[source:" in draft or "## Sources" in draft),
            ("Includes quantitative evidence", bool(re.search(r"\d", draft))),
            ("Has an executive summary", "summary" in draft.lower()),
            ("Concise (under 600 words)", len(draft.split()) < 600),
        ]
        passed = sum(ok for _, ok in checks)
        verdict = "PASS" if passed >= 3 else "NEEDS REVISION"
        lines = [f"Review verdict: {verdict} ({passed}/{len(checks)} checks)"]
        lines += [f"- {'✓' if ok else '✗'} {name}" for name, ok in checks]
        return "\n".join(lines), []

    def _communicator(self, prompt: str, history) -> tuple[str, list[ToolCall]]:
        task = _section(prompt, "Task")
        instruction = _section(prompt, "Your instruction")
        if history:
            name, args, result = history[-1]
            target = args.get("to") or args.get("channel")
            return f"Prepared {'a Slack message' if name == 'post_slack_message' else 'an email'} for {target}. {result}", []
        blocks = _context_blocks(_context(prompt))
        body = blocks.get("writer") or next(iter(blocks.values()), task)
        both = f"{task} {instruction}"
        if "slack" in both.lower():
            channel = (re.search(r"#[\w-]+", both) or [None])[0] or "#general"
            return "Posting the summary to Slack.", [ToolCall("post_slack_message", {"channel": channel, "text": body[:3000]})]
        to = (EMAIL_RE.search(both) or [None])[0] or "leadership@northwind.example"
        subject = re.sub(r"\s+", " ", task.split(".")[0])[:90]
        return "Drafting the email.", [ToolCall("send_email", {"to": to, "subject": subject, "body": body[:6000]})]
