import asyncio
import json

import pytest

from hiveops import tools
from hiveops.config import Settings
from hiveops.db import Database
from hiveops.models import Dataset
from hiveops.tools import ToolContext, ToolError, parse_csv, safe_eval

CSV = b"month,region,revenue,units\n2026-01,EMEA,100.5,3\n2026-01,APAC,50,2\n2026-02,EMEA,\"1,000\",5\n2026-02,APAC,25,1\n"


def test_parse_csv_infers_types():
    columns, rows = parse_csv(CSV)
    assert columns == [
        {"name": "month", "type": "string"},
        {"name": "region", "type": "string"},
        {"name": "revenue", "type": "number"},
        {"name": "units", "type": "number"},
    ]
    assert rows[2]["revenue"] == 1000.0


@pytest.mark.parametrize("data", [b"", b"a,b\n"])
def test_parse_csv_rejects_empty_files(data):
    with pytest.raises(ValueError):
        parse_csv(data)


@pytest.mark.parametrize(
    ("expr", "value"),
    [("2 + 3 * 4", 14), ("(4820000 - 4085000) / 4085000 * 100", (4820000 - 4085000) / 4085000 * 100), ("-2 ** 2", -4), ("7 % 3", 1)],
)
def test_calculator(expr, value):
    assert safe_eval(expr) == pytest.approx(value)


@pytest.mark.parametrize("expr", ["__import__('os').system('ls')", "a + 1", "open('x')", "2 ** 1000", "1 / 0", "(1).real"])
def test_calculator_rejects_anything_but_arithmetic(expr):
    with pytest.raises(ToolError):
        safe_eval(expr)


@pytest.fixture
def ctx(tmp_path):
    async def setup():
        db = Database(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
        await db.init()
        columns, rows = parse_csv(CSV)
        async with db.session() as s, s.begin():
            s.add(Dataset(name="sales", columns=columns, rows=rows, row_count=len(rows)))
        return ToolContext(db=db, settings=Settings())

    return asyncio.run(setup())


def call(ctx, name, args):
    return asyncio.run(tools.execute(name, ctx, args))


def test_query_dataset_groups_and_sorts(ctx):
    out = json.loads(call(ctx, "query_dataset", {"dataset": "sales", "metric": "revenue", "agg": "sum", "group_by": "region"}))
    assert out["rows"] == [{"key": "EMEA", "value": 1100.5}, {"key": "APAC", "value": 75.0}]


def test_query_dataset_filters_counts_and_averages(ctx):
    count = json.loads(call(ctx, "query_dataset", {"dataset": "sales", "agg": "count", "filters": {"region": "emea"}}))
    assert count["rows"] == [{"key": "all", "value": 2}]
    avg = json.loads(call(ctx, "query_dataset", {"dataset": "sales", "metric": "units", "agg": "avg", "group_by": "month", "sort": "key"}))
    assert avg["rows"] == [{"key": "2026-01", "value": 2.5}, {"key": "2026-02", "value": 3.0}]


@pytest.mark.parametrize(
    "args",
    [
        {"dataset": "missing", "agg": "sum", "metric": "revenue"},
        {"dataset": "sales", "agg": "sum", "metric": "region"},
        {"dataset": "sales", "agg": "median", "metric": "revenue"},
        {"dataset": "sales", "agg": "sum", "metric": "revenue", "group_by": "nope"},
        {"dataset": "sales", "agg": "count", "filters": {"nope": 1}},
    ],
)
def test_query_dataset_validates_arguments(ctx, args):
    with pytest.raises(ToolError):
        call(ctx, "query_dataset", args)


def test_describe_and_list_datasets(ctx):
    assert json.loads(call(ctx, "list_datasets", {}))[0]["name"] == "sales"
    described = json.loads(call(ctx, "describe_dataset", {"dataset": "sales"}))
    assert described["rowCount"] == 4 and len(described["sample"]) == 3


def test_send_email_validates_recipient(ctx):
    with pytest.raises(ToolError):
        call(ctx, "send_email", {"to": "not-an-email", "subject": "x", "body": "y"})
    assert "delivered" in call(ctx, "send_email", {"to": "a@b.example", "subject": "Hi", "body": "Body"})


def test_side_effect_tools_require_approval():
    assert {n for n, t in tools.TOOLS.items() if t.requires_approval} == {"send_email", "post_slack_message"}


def test_unknown_tool(ctx):
    with pytest.raises(ToolError):
        call(ctx, "rm_rf", {})
