"""Demo data: a fictional company's documents, a sales dataset, workflow templates and an eval suite."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select

from . import rag
from .models import Dataset, Document, EvalSuite, Run, Workflow
from .tools import parse_csv

log = logging.getLogger("hiveops")
DATA = Path(__file__).parent / "seed_data"

TEMPLATES = [
    {
        "name": "Quarterly Business Review",
        "description": "Research the quarter, analyse revenue, draft an executive brief, get it approved, then email leadership.",
        "mode": "custom",
        "default_task": "Prepare the Q3 2026 business review brief for leadership and email it to leadership@northwind.example.",
        "steps": [
            {
                "agent": "researcher",
                "instruction": "Summarize Q3 2026 results, risks and Q4 priorities from the business review.",
                "approval": False,
            },
            {"agent": "analyst", "instruction": "Break down 2026 revenue by region and show the monthly trend.", "approval": False},
            {"agent": "writer", "instruction": "Write a one-page executive brief for the leadership team.", "approval": True},
            {"agent": "communicator", "instruction": "Email the approved brief to leadership@northwind.example.", "approval": False},
        ],
    },
    {
        "name": "Contract Risk Review",
        "description": "Extract key contract terms, check them for risk, and produce a reviewed summary for Legal.",
        "mode": "custom",
        "default_task": "Review the Acme Cloud contract for renewal deadlines, fees and liability risks.",
        "steps": [
            {
                "agent": "researcher",
                "instruction": "Extract renewal, notice period, fees, termination and liability terms of the Acme Cloud agreement.",
                "approval": False,
            },
            {"agent": "writer", "instruction": "Write a contract risk summary with the deadlines Legal must act on.", "approval": False},
            {"agent": "reviewer", "instruction": "Verify every claim is cited and flag anything unsupported.", "approval": True},
        ],
    },
    {
        "name": "Policy Q&A",
        "description": "Answer an employee question from the handbook, with citations.",
        "mode": "custom",
        "default_task": "What is our expense approval policy and what is the hotel limit in London?",
        "steps": [
            {"agent": "researcher", "instruction": "Find the exact policy rules that answer the question.", "approval": False},
            {"agent": "writer", "instruction": "Answer the employee clearly and cite the handbook.", "approval": False},
        ],
    },
    {
        "name": "Autopilot",
        "description": "The Supervisor agent plans the work and routes each step to the right specialist.",
        "mode": "auto",
        "default_task": "Analyze 2026 revenue by product and summarize what our pricing FAQ says about each plan.",
        "steps": [],
    },
]

EVAL_CASES = [
    {
        "question": "How many days of paid time off do full-time employees get?",
        "expected": ["25 days"],
        "expected_source": "employee_handbook.md",
    },
    {
        "question": "Who must approve expenses above $5,000?",
        "expected": ["Finance Director", "Priya Raman"],
        "expected_source": "employee_handbook.md",
    },
    {"question": "What is the hotel limit per night in London?", "expected": ["$350"], "expected_source": "employee_handbook.md"},
    {"question": "How much does the Growth plan cost per month?", "expected": ["$199"], "expected_source": "product_faq.md"},
    {"question": "What uptime SLA do Enterprise customers receive?", "expected": ["99.9%"], "expected_source": "product_faq.md"},
    {"question": "How long is raw event data retained on the Growth plan?", "expected": ["13 months"], "expected_source": "product_faq.md"},
    {"question": "What was total revenue in Q3 2026?", "expected": ["$4.82 million"], "expected_source": "q3_2026_business_review.md"},
    {"question": "Which region grew fastest in Q3 2026?", "expected": ["EMEA"], "expected_source": "q3_2026_business_review.md"},
    {
        "question": "By when must Northwind send the non-renewal notice to Acme Cloud?",
        "expected": ["December 2, 2026"],
        "expected_source": "acme_cloud_contract_summary.md",
    },
    {
        "question": "What is the liability cap in the Acme Cloud agreement?",
        "expected": ["12 months"],
        "expected_source": "acme_cloud_contract_summary.md",
    },
]

DEMO_RUNS = [
    ("Quarterly Business Review", None),
    ("Contract Risk Review", None),
    ("Policy Q&A", None),
    ("Autopilot", None),
    ("Autopilot", "What does our remote work policy say, and how did EMEA revenue trend in 2026? Notify #leadership on Slack."),
]


async def seed(rt) -> None:
    db = rt.db
    async with db.session() as s:
        if (await s.execute(select(func.count()).select_from(Workflow))).scalar():
            return  # already seeded

    for path in sorted(DATA.glob("*.md")):
        await rag.ingest(db, path.name, path.read_bytes())
    columns, rows = parse_csv((DATA / "sales_2026.csv").read_bytes())
    async with db.session() as s, s.begin():
        s.add(Dataset(name="sales_2026", source="csv_upload", columns=columns, rows=rows, row_count=len(rows)))
        for t in TEMPLATES:
            s.add(Workflow(is_template=True, **t))
        s.add(EvalSuite(name="Knowledge base QA", description="Factual questions answered from the company documents.", cases=EVAL_CASES))
    log.info("seeded demo documents, dataset, workflows and eval suite")

    if rt.settings.seed_demo_runs:
        async with db.session() as s:
            workflows = {w.name: w for w in (await s.execute(select(Workflow))).scalars()}
            docs = (await s.execute(select(func.count()).select_from(Document))).scalar()
        for name, task in DEMO_RUNS:
            run = await create_run(rt, workflows[name], task)
            log.info("queued demo run %s (%s, %d docs)", run.id, name, docs)


async def create_run(rt, workflow: Workflow, task: str | None = None) -> Run:
    async with rt.db.session() as s, s.begin():
        run = Run(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            mode=workflow.mode,
            steps=workflow.steps,
            task=(task or workflow.default_task).strip(),
            provider=rt.provider.name,
            model=rt.provider.model,
        )
        s.add(run)
    await rt.enqueue_run(run.id)
    return run
