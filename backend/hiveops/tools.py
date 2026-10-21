"""Tools agents can call. Tools with side effects require human approval."""

from __future__ import annotations

import ast
import csv
import io
import json
import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select

from . import rag
from .config import Settings
from .db import Database
from .models import Dataset, OutboxMessage


@dataclass
class ToolContext:
    db: Database
    settings: Settings
    run_id: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[[ToolContext, dict[str, Any]], Awaitable[str]]
    requires_approval: bool = False

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- datasets


def parse_csv(data: bytes) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("The CSV file has no header row.")
    raw = [row for row in reader if any((v or "").strip() for v in row.values())]
    if not raw:
        raise ValueError("The CSV file has no data rows.")
    columns = []
    for name in reader.fieldnames:
        values = [(r.get(name) or "").strip() for r in raw]
        numeric = all(_is_number(v) for v in values if v) and any(values)
        columns.append({"name": name.strip(), "type": "number" if numeric else "string"})
    rows = []
    for r in raw:
        row = {}
        for col in columns:
            v = (r.get(col["name"]) or "").strip()
            row[col["name"]] = (float(v.replace(",", "")) if v else None) if col["type"] == "number" else v
        rows.append(row)
    return columns, rows


def _is_number(v: str) -> bool:
    try:
        float(v.replace(",", ""))
        return True
    except ValueError:
        return False


async def _get_dataset(ctx: ToolContext, name: str) -> Dataset:
    async with ctx.db.session() as s:
        ds = (await s.execute(select(Dataset).where(Dataset.name == name))).scalar()
    if ds is None:
        raise ToolError(f"No dataset named {name!r}. Call list_datasets to see what is available.")
    return ds


async def list_datasets(ctx: ToolContext, args: dict[str, Any]) -> str:
    async with ctx.db.session() as s:
        rows = (await s.execute(select(Dataset).order_by(Dataset.name))).scalars().all()
    return json.dumps([{"name": d.name, "rows": d.row_count, "columns": [c["name"] for c in d.columns]} for d in rows])


async def describe_dataset(ctx: ToolContext, args: dict[str, Any]) -> str:
    ds = await _get_dataset(ctx, str(args.get("dataset", "")))
    return json.dumps({"name": ds.name, "rowCount": ds.row_count, "columns": ds.columns, "sample": ds.rows[:3]})


AGGREGATES: dict[str, Callable[[list[float]], float]] = {
    "sum": sum,
    "avg": lambda xs: sum(xs) / len(xs) if xs else 0.0,
    "min": lambda xs: min(xs) if xs else 0.0,
    "max": lambda xs: max(xs) if xs else 0.0,
    "count": len,
}


async def query_dataset(ctx: ToolContext, args: dict[str, Any]) -> str:
    ds = await _get_dataset(ctx, str(args.get("dataset", "")))
    columns = {c["name"]: c["type"] for c in ds.columns}
    agg = str(args.get("agg", "sum")).lower()
    metric = args.get("metric")
    group_by = args.get("group_by")
    filters = args.get("filters") or {}
    if agg not in AGGREGATES:
        raise ToolError(f"agg must be one of {sorted(AGGREGATES)}")
    if agg != "count" and (metric not in columns or columns[metric] != "number"):
        raise ToolError(f"metric must be a numeric column: {[c for c, t in columns.items() if t == 'number']}")
    if group_by and group_by not in columns:
        raise ToolError(f"group_by must be one of {list(columns)}")
    for col in filters:
        if col not in columns:
            raise ToolError(f"Unknown filter column {col!r}")

    def keep(row: dict[str, Any]) -> bool:
        return all(str(row.get(c, "")).lower() == str(v).lower() for c, v in filters.items())

    groups: dict[str, list[float]] = {}
    for row in filter(keep, ds.rows):
        key = str(row.get(group_by)) if group_by else "all"
        value = row.get(metric) if metric else 1.0
        if value is not None or agg == "count":
            groups.setdefault(key, []).append(float(value or 0))
    out = [{"key": k, "value": round(AGGREGATES[agg](v), 4)} for k, v in groups.items()]
    if args.get("sort") == "key":
        out.sort(key=lambda r: r["key"])
    else:
        out.sort(key=lambda r: r["value"], reverse=True)
    limit = int(args.get("limit", 50))
    return json.dumps({"dataset": ds.name, "metric": metric, "agg": agg, "group_by": group_by, "rows": out[:limit]})


# ------------------------------------------------------------------- search


async def search_documents(ctx: ToolContext, args: dict[str, Any]) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolError("query is required")
    k = max(1, min(int(args.get("k", 4)), 10))
    hits = await rag.search(ctx.db, query, k=k)
    return json.dumps([h.as_dict() for h in hits])


# --------------------------------------------------------------- calculator

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def safe_eval(expression: str) -> float:
    """Arithmetic only: numbers, + - * / % ** and parentheses. No names, calls or attributes."""

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            if isinstance(node.op, ast.Pow) and abs(ev(node.right)) > 100:
                raise ToolError("exponent too large")
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ToolError("Only arithmetic expressions are allowed")

    if len(expression) > 200:
        raise ToolError("expression too long")
    try:
        return ev(ast.parse(expression, mode="eval"))
    except (SyntaxError, ZeroDivisionError) as exc:
        raise ToolError(str(exc)) from exc


async def calculator(ctx: ToolContext, args: dict[str, Any]) -> str:
    return json.dumps({"expression": args.get("expression"), "result": safe_eval(str(args.get("expression", "")))})


# ------------------------------------------------------------- integrations


async def send_email(ctx: ToolContext, args: dict[str, Any]) -> str:
    to, subject, body = str(args.get("to", "")), str(args.get("subject", "")), str(args.get("body", ""))
    if "@" not in to:
        raise ToolError("to must be an email address")
    async with ctx.db.session() as s, s.begin():
        s.add(
            OutboxMessage(
                run_id=ctx.run_id,
                channel="email",
                recipient=to,
                subject=subject[:255],
                body=body,
                detail="Delivered to outbox (connect an SMTP relay to send externally)",
            )
        )
    return f"Email to {to} delivered."


async def post_slack_message(ctx: ToolContext, args: dict[str, Any]) -> str:
    channel, body = str(args.get("channel", "#general")), str(args.get("text", ""))
    delivered, detail = True, "Recorded in outbox (set SLACK_WEBHOOK_URL to post to Slack)"
    if ctx.settings.slack_webhook_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(ctx.settings.slack_webhook_url, json={"text": f"*{channel}*\n{body}"})
            delivered, detail = resp.is_success, f"Slack webhook HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            delivered, detail = False, f"Slack webhook failed: {exc}"
    async with ctx.db.session() as s, s.begin():
        s.add(OutboxMessage(run_id=ctx.run_id, channel="slack", recipient=channel, body=body, delivered=delivered, detail=detail))
    if not delivered:
        raise ToolError(detail)
    return f"Posted to {channel}."


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "search_documents",
            "Semantic + keyword search over the uploaded knowledge base. Returns the most relevant passages with their source document.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for"},
                    "k": {"type": "integer", "description": "Number of passages (1-10)", "default": 4},
                },
                "required": ["query"],
            },
            search_documents,
        ),
        Tool("list_datasets", "List connected tabular datasets with their columns.", {"type": "object", "properties": {}}, list_datasets),
        Tool(
            "describe_dataset",
            "Show a dataset's columns, types, row count and sample rows.",
            {"type": "object", "properties": {"dataset": {"type": "string"}}, "required": ["dataset"]},
            describe_dataset,
        ),
        Tool(
            "query_dataset",
            "Aggregate a dataset: agg(metric) optionally grouped by a column and filtered by exact column values.",
            {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string"},
                    "metric": {"type": "string", "description": "Numeric column (omit for count)"},
                    "agg": {"type": "string", "enum": ["sum", "avg", "min", "max", "count"]},
                    "group_by": {"type": "string"},
                    "filters": {"type": "object", "description": 'Exact-match filters, e.g. {"region": "EMEA"}'},
                    "sort": {"type": "string", "enum": ["value", "key"]},
                    "limit": {"type": "integer"},
                },
                "required": ["dataset", "agg"],
            },
            query_dataset,
        ),
        Tool(
            "calculator",
            "Evaluate an arithmetic expression exactly, e.g. (4820000 - 4085000) / 4085000 * 100.",
            {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
            calculator,
        ),
        Tool(
            "send_email",
            "Send an email. Requires human approval before it is sent.",
            {
                "type": "object",
                "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["to", "subject", "body"],
            },
            send_email,
            requires_approval=True,
        ),
        Tool(
            "post_slack_message",
            "Post a message to a Slack channel. Requires human approval before it is posted.",
            {
                "type": "object",
                "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
                "required": ["channel", "text"],
            },
            post_slack_message,
            requires_approval=True,
        ),
    ]
}


async def execute(name: str, ctx: ToolContext, args: dict[str, Any]) -> str:
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"Unknown tool {name!r}")
    return await tool.fn(ctx, args)
