"""Aggregates for the command-center dashboard."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .agents import AGENTS
from .db import Database
from .models import Approval, EvalRun, Run, RunEvent

FINISHED = {"completed", "failed", "rejected"}


def _pct_change(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


async def overview(db: Database, days: int = 14) -> dict:
    now = datetime.now(UTC)
    since = now - timedelta(days=60)
    async with db.session() as s:
        runs = (await s.execute(select(Run).where(Run.created_at >= since))).scalars().all()
        approvals = (await s.execute(select(Approval).where(Approval.created_at >= since))).scalars().all()
        llm_events = (
            await s.execute(
                select(RunEvent.agent, RunEvent.type, RunEvent.data).where(
                    RunEvent.ts >= now - timedelta(days=30), RunEvent.type.in_(["llm_call", "agent_error", "tool_error"])
                )
            )
        ).all()
        latest_eval = (await s.execute(select(EvalRun).where(EvalRun.status == "completed").order_by(EvalRun.created_at.desc()))).scalar()

    def aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    # ---- KPIs: this 30-day window vs the previous one
    cur = [r for r in runs if aware(r.created_at) >= now - timedelta(days=30)]
    prev = [r for r in runs if now - timedelta(days=60) <= aware(r.created_at) < now - timedelta(days=30)]
    week = [r for r in runs if aware(r.created_at) >= now - timedelta(days=7)]

    def success_rate(rs: list[Run]) -> float | None:
        done = [r for r in rs if r.status in FINISHED]
        return round(sum(r.status == "completed" for r in done) / len(done) * 100, 1) if done else None

    decided = [a for a in approvals if a.status in ("approved", "rejected")]
    cost_cur = sum(r.cost for r in cur)
    finished_cur = [r for r in cur if r.status in FINISHED and r.active_ms]
    active_agents = {a for r in week for a in (r.plan or [])}

    kpis = {
        "spend": round(cost_cur, 4),
        "spendChange": _pct_change(cost_cur, sum(r.cost for r in prev)),
        "runs": len(cur),
        "runsChange": _pct_change(len(cur), len(prev)),
        "successRate": success_rate(cur),
        "approvalRate": round(sum(a.status == "approved" for a in decided) / len(decided) * 100, 1) if decided else None,
        "pendingApprovals": sum(a.status == "pending" for a in approvals),
        "activeAgents": len(active_agents),
        "totalAgents": len(AGENTS),
        "avgLatencyMs": round(sum(r.active_ms for r in finished_cur) / len(finished_cur)) if finished_cur else None,
        "tokens": sum(r.tokens_in + r.tokens_out for r in cur),
    }

    # ---- daily cost and run counts
    daily: dict[str, dict] = {}
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).date().isoformat()
        daily[day] = {"date": day, "cost": 0.0, "runs": 0, "failed": 0}
    for r in runs:
        day = aware(r.created_at).date().isoformat()
        if day in daily:
            daily[day]["cost"] += r.cost
            daily[day]["runs"] += 1
            daily[day]["failed"] += r.status == "failed"
    for d in daily.values():
        d["cost"] = round(d["cost"], 5)

    # ---- routing map: how work flows between agents
    edges: Counter[tuple[str, str]] = Counter()
    stage_counts: Counter[str] = Counter()
    for r in cur:
        path = ["intake", *(r.plan or []), "deliver" if r.status == "completed" else r.status]
        for a, b in zip(path, path[1:], strict=False):
            edges[(a, b)] += 1
        for node in path:
            stage_counts[node] += 1

    # ---- per-agent health
    stats: dict[str, dict] = defaultdict(lambda: {"calls": 0, "latency": 0, "tokens": 0, "cost": 0.0, "errors": 0})
    for agent, type_, data in llm_events:
        st = stats[agent or "system"]
        if type_ == "llm_call":
            st["calls"] += 1
            st["latency"] += int(data.get("latencyMs", 0))
            st["tokens"] += int(data.get("tokensIn", 0)) + int(data.get("tokensOut", 0))
            st["cost"] += float(data.get("cost", 0.0))
        else:
            st["errors"] += 1
    agent_health = []
    for spec in AGENTS.values():
        st = stats.get(spec.id, {"calls": 0, "latency": 0, "tokens": 0, "cost": 0.0, "errors": 0})
        calls = st["calls"]
        agent_health.append(
            {
                "id": spec.id,
                "name": spec.name,
                "color": spec.color,
                "calls": calls,
                "avgLatencyMs": round(st["latency"] / calls) if calls else None,
                "tokens": st["tokens"],
                "cost": round(st["cost"], 5),
                "errors": st["errors"],
                "errorRate": round(st["errors"] / (calls + st["errors"]) * 100, 1) if calls + st["errors"] else 0.0,
            }
        )

    pending = sorted((a for a in approvals if a.status == "pending"), key=lambda a: a.created_at, reverse=True)[:5]
    recent = sorted(runs, key=lambda r: r.created_at, reverse=True)[:8]
    status_counts = Counter(r.status for r in cur)

    return {
        "kpis": kpis,
        "daily": list(daily.values()),
        "routing": {
            "edges": [{"from": a, "to": b, "count": c} for (a, b), c in edges.most_common()],
            "stages": dict(stage_counts),
        },
        "agents": agent_health,
        "statusCounts": dict(status_counts),
        "pendingApprovals": [approval_summary(a) for a in pending],
        "recentRuns": [run_summary(r) for r in recent],
        "latestEval": {"id": latest_eval.id, "metrics": latest_eval.metrics, "createdAt": latest_eval.created_at.isoformat()}
        if latest_eval
        else None,
    }


def run_summary(r: Run) -> dict:
    return {
        "id": r.id,
        "workflowId": r.workflow_id,
        "workflowName": r.workflow_name,
        "mode": r.mode,
        "task": r.task,
        "status": r.status,
        "plan": r.plan,
        "tokens": r.tokens_in + r.tokens_out,
        "cost": round(r.cost, 6),
        "latencyMs": r.active_ms,
        "createdAt": r.created_at.isoformat(),
        "finishedAt": r.finished_at.isoformat() if r.finished_at else None,
    }


def approval_summary(a: Approval) -> dict:
    return {
        "id": a.id,
        "runId": a.run_id,
        "kind": a.kind,
        "agent": a.agent,
        "title": a.title,
        "payload": a.payload,
        "status": a.status,
        "comment": a.comment,
        "createdAt": a.created_at.isoformat(),
        "decidedAt": a.decided_at.isoformat() if a.decided_at else None,
    }
