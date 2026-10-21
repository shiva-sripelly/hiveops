"""Offline evaluation of the RAG pipeline.

For each case: retrieve passages, generate an answer with the configured model,
then score

* retrieval hit: the expected source document is in the top-k passages
* answer recall: share of expected key facts present in the answer
* groundedness: share of answer sentences supported by the retrieved passages
  (token overlap, a lightweight faithfulness proxy that needs no judge model)
* latency, tokens and cost

A case passes when retrieval hits, recall ≥ 0.6 and groundedness ≥ 0.6.
"""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import update

from . import rag
from .llm import LLMError
from .models import EvalRun, EvalSuite, now

RAG_SYSTEM = (
    "Answer the question using only the context passages. Use short bullet points and cite each claim as "
    "[source: <document name>]. If the answer is not in the context, say so."
)
TOP_K = 4


def groundedness(answer: str, passages: list[str]) -> float:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", re.sub(r"\[source: .+?\]", "", answer)) if len(rag.tokens(s)) >= 4]
    if not sentences:
        return 0.0
    context = set(rag.tokens(" ".join(passages)))
    supported = sum(1 for s in sentences if len(set(rag.tokens(s)) & context) / len(set(rag.tokens(s))) >= 0.7)
    return supported / len(sentences)


def recall(answer: str, expected: list[str]) -> float:
    if not expected:
        return 1.0
    low = answer.lower()
    return sum(1 for e in expected if e.lower() in low) / len(expected)


async def run_case(rt, case: dict[str, Any]) -> dict[str, Any]:
    question = case["question"]
    started = time.perf_counter()
    hits = await rag.search(rt.db, question, k=TOP_K)
    context = "\n".join(f"[source: {h.document}]\n{h.text}" for h in hits)
    try:
        result = await rt.provider.complete(
            RAG_SYSTEM, [{"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"}], [], agent="rag"
        )
        answer, error = result.text, None
        tokens_in, tokens_out, cost = result.tokens_in, result.tokens_out, result.cost
    except LLMError as exc:
        answer, error, tokens_in, tokens_out, cost = "", str(exc), 0, 0, 0.0
    latency = int((time.perf_counter() - started) * 1000)
    docs = [h.document for h in hits]
    hit = case.get("expected_source") in docs if case.get("expected_source") else True
    r = recall(answer, case.get("expected", []))
    g = groundedness(answer, [h.text for h in hits])
    return {
        "question": question,
        "answer": answer,
        "error": error,
        "retrieved": docs,
        "expectedSource": case.get("expected_source"),
        "retrievalHit": hit,
        "recall": round(r, 3),
        "groundedness": round(g, 3),
        "passed": bool(hit and r >= 0.6 and g >= 0.6 and not error),
        "latencyMs": latency,
        "tokens": tokens_in + tokens_out,
        "cost": cost,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results) or 1
    return {
        "cases": len(results),
        "passRate": round(sum(r["passed"] for r in results) / n, 3),
        "retrievalHitRate": round(sum(r["retrievalHit"] for r in results) / n, 3),
        "avgRecall": round(sum(r["recall"] for r in results) / n, 3),
        "avgGroundedness": round(sum(r["groundedness"] for r in results) / n, 3),
        "avgLatencyMs": round(sum(r["latencyMs"] for r in results) / n),
        "totalTokens": sum(r["tokens"] for r in results),
        "totalCost": round(sum(r["cost"] for r in results), 6),
    }


async def run_suite(rt, suite: EvalSuite, eval_run_id: str) -> None:
    results = []
    try:
        for case in suite.cases:
            results.append(await run_case(rt, case))
        status = "completed"
    except Exception as exc:  # keep partial results
        results.append(
            {
                "question": "(suite error)",
                "error": str(exc),
                "passed": False,
                "retrievalHit": False,
                "recall": 0,
                "groundedness": 0,
                "latencyMs": 0,
                "tokens": 0,
                "cost": 0,
            }
        )
        status = "failed"
    async with rt.db.session() as s, s.begin():
        await s.execute(
            update(EvalRun)
            .where(EvalRun.id == eval_run_id)
            .values(status=status, results=results, metrics=summarize(results), finished_at=now())
        )
