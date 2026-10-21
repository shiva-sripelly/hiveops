"""End-to-end tests through the HTTP API, the LangGraph orchestrator and the workers."""

import time

from conftest import wait_for, workflow_id

from hiveops.llm import LLMError


def create_workflow(client, steps, name="Test flow", mode="custom", task=""):
    res = client.post("/api/workflows", json={"name": name, "mode": mode, "steps": steps, "default_task": task})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def start(client, wf_id, task="") -> str:
    res = client.post(f"/api/workflows/{wf_id}/run", json={"task": task})
    assert res.status_code == 202, res.text
    return res.json()["id"]


def pending_for(client, run_id):
    return [a for a in client.get("/api/approvals", params={"status": "pending"}).json() if a["runId"] == run_id]


# ------------------------------------------------------------------ basics


def test_health_and_seed(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["databaseOk"] and health["llm"]["simulated"]
    assert len(client.get("/api/documents").json()) == 4
    assert client.get("/api/datasets").json()[0]["rows"] == 108
    assert {w["name"] for w in client.get("/api/workflows").json()} >= {"Quarterly Business Review", "Autopilot", "Policy Q&A"}
    assert len(client.get("/api/agents").json()) == 6


def test_document_upload_search_and_delete(client):
    res = client.post("/api/documents", files={"file": ("notes.md", b"## Parking\nVisitor parking is in garage B, level 2.", "text/markdown")})
    assert res.status_code == 201 and res.json()["chunks"] == 1
    hits = client.post("/api/documents/search", json={"query": "where is visitor parking", "k": 3}).json()
    assert hits[0]["document"] == "notes.md"
    assert client.delete(f"/api/documents/{res.json()['id']}").status_code == 204
    assert client.delete(f"/api/documents/{res.json()['id']}").status_code == 404
    bad = client.post("/api/documents", files={"file": ("image.png", b"\x89PNG", "image/png")})
    assert bad.status_code == 400


def test_dataset_upload(client):
    csv = b"team,headcount\nSales,12\nSupport,8\n"
    res = client.post("/api/datasets", files={"file": ("Team Sizes.csv", csv, "text/csv")})
    assert res.status_code == 201
    assert res.json()["name"] == "team_sizes" and res.json()["columns"][1] == {"name": "headcount", "type": "number"}
    assert client.post("/api/datasets", files={"file": ("Team Sizes.csv", csv, "text/csv")}).status_code == 409
    assert client.post("/api/datasets", files={"file": ("data.txt", csv, "text/plain")}).status_code == 400


def test_workflow_validation_and_crud(client):
    assert client.post("/api/workflows", json={"name": "x", "mode": "custom", "steps": []}).status_code == 422
    assert client.post("/api/workflows", json={"name": "x", "steps": [{"agent": "planner"}]}).status_code == 422
    assert client.post("/api/workflows", json={"name": "x", "steps": [{"agent": "ghost"}]}).status_code == 422
    wf = create_workflow(client, [{"agent": "researcher"}])
    updated = client.put(f"/api/workflows/{wf}", json={"name": "Renamed", "steps": [{"agent": "writer", "approval": True}]})
    assert updated.json()["name"] == "Renamed" and updated.json()["steps"][0]["approval"] is True
    assert client.post(f"/api/workflows/{wf}/run", json={"task": "  "}).status_code == 422  # no task and no default
    assert client.delete(f"/api/workflows/{wf}").status_code == 204
    assert client.get(f"/api/workflows/{wf}").status_code == 404


# ------------------------------------------------------------- execution


def test_custom_workflow_runs_end_to_end_with_live_log(client):
    run_id = start(client, workflow_id(client, "Policy Q&A"), "What is the hotel limit in London?")
    run = wait_for(client, run_id, {"completed"})
    assert run["plan"] == ["researcher", "writer"]
    assert "$350" in run["output"] and "employee_handbook.md" in run["sources"]
    assert run["tokensIn"] > 0 and run["cost"] > 0
    seqs = [e["seq"] for e in run["events"]]
    assert seqs == list(range(1, len(seqs) + 1))  # gap-free, ordered audit log
    types = {e["type"] for e in run["events"]}
    assert {"run_started", "agent_start", "llm_call", "tool_call", "tool_result", "agent_output", "run_finished"} <= types

    # The SSE endpoint replays the full history for a finished run, then ends.
    with client.stream("GET", f"/api/runs/{run_id}/stream") as stream:
        body = "".join(stream.iter_text())
    assert body.count("event: run_event") == len(seqs) and "event: end" in body
    with client.stream("GET", f"/api/runs/{run_id}/stream?after={len(seqs) - 2}") as stream:
        assert "".join(stream.iter_text()).count("event: run_event") == 2


def test_supervisor_plans_dynamically(client):
    run_id = start(client, workflow_id(client, "Autopilot"), "Compare 2026 revenue by region in the sales data.")
    run = wait_for(client, run_id, {"completed"})
    assert "analyst" in run["plan"] and run["plan"][-1] == "writer"
    plan_event = next(e for e in run["events"] if e["type"] == "plan")
    assert [s["agent"] for s in plan_event["data"]["steps"]] == run["plan"]
    assert "Data insights" in run["output"]


def test_step_approval_reject_stops_the_run(client):
    wf = create_workflow(client, [{"agent": "researcher", "approval": True}, {"agent": "writer"}], task="What is the PTO policy?")
    run_id = start(client, wf)
    wait_for(client, run_id, {"awaiting_approval"})
    [approval] = pending_for(client, run_id)
    assert approval["kind"] == "step_output" and approval["agent"] == "researcher"

    res = client.post(f"/api/approvals/{approval['id']}/decide", json={"approved": False, "comment": "Wrong policy"})
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    run = wait_for(client, run_id, {"rejected"})
    assert run["plan"] == ["researcher"]  # the writer never ran
    assert client.post(f"/api/approvals/{approval['id']}/decide", json={"approved": True}).status_code == 409


def test_approved_email_is_sent_exactly_once(client):
    run_id = start(client, workflow_id(client, "Quarterly Business Review"))
    wait_for(client, run_id, {"awaiting_approval"})
    [writer_gate] = pending_for(client, run_id)
    assert writer_gate["kind"] == "step_output"
    client.post(f"/api/approvals/{writer_gate['id']}/decide", json={"approved": True})

    wait_for(client, run_id, {"awaiting_approval"}) if not pending_for(client, run_id) else None
    deadline = time.time() + 10
    while not (email_gate := pending_for(client, run_id)) and time.time() < deadline:
        time.sleep(0.05)
    [email_gate] = email_gate
    assert email_gate["payload"]["tool"] == "send_email"
    assert email_gate["payload"]["args"]["to"] == "leadership@northwind.example"
    assert client.get("/api/outbox").json() == []  # nothing sent before approval

    client.post(f"/api/approvals/{email_gate['id']}/decide", json={"approved": True, "comment": "Ship it"})
    run = wait_for(client, run_id, {"completed"})
    outbox = client.get("/api/outbox").json()
    assert len(outbox) == 1 and outbox[0]["recipient"] == "leadership@northwind.example"
    assert run["deliveries"][0]["delivered"] is True
    assert [a["status"] for a in run["approvals"]] == ["approved", "approved"]


def test_rejected_email_is_never_sent(client):
    wf = create_workflow(client, [{"agent": "writer"}, {"agent": "communicator"}], task="Send the PTO summary to hr@northwind.example")
    run_id = start(client, wf)
    wait_for(client, run_id, {"awaiting_approval"})
    [gate] = pending_for(client, run_id)
    client.post(f"/api/approvals/{gate['id']}/decide", json={"approved": False, "comment": "Not yet"})
    run = wait_for(client, run_id, {"completed"})
    assert client.get("/api/outbox").json() == []
    assert "send_email rejected by reviewer" in run["output"]


def test_cancel_a_run_waiting_for_approval(client):
    wf = create_workflow(client, [{"agent": "researcher", "approval": True}], task="Summarize the SLA")
    run_id = start(client, wf)
    wait_for(client, run_id, {"awaiting_approval"})
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "failed" and run["error"] == "Cancelled by user"
    assert run["approvals"][0]["status"] == "cancelled"
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409


class FailingProvider:
    name, model, simulated = "broken", "broken-1", False

    async def complete(self, *args, **kwargs):
        raise LLMError("rate limited after 3 retries")


def test_llm_failures_fail_the_run_cleanly(client):
    client.app.state.rt.provider = FailingProvider()
    run_id = start(client, workflow_id(client, "Policy Q&A"), "Anything")
    run = wait_for(client, run_id, {"failed"})
    assert "rate limited" in run["error"]
    assert any(e["type"] == "agent_error" for e in run["events"])


# ------------------------------------------------------------ evals & dashboard


def test_evaluation_suite(client):
    suite = client.get("/api/evals/suites").json()[0]
    assert client.post(f"/api/evals/suites/{suite['id']}/run").status_code == 202
    deadline = time.time() + 20
    while time.time() < deadline:
        latest = client.get("/api/evals/runs").json()[0]
        if latest["status"] != "running":
            break
        time.sleep(0.1)
    assert latest["status"] == "completed"
    m = latest["metrics"]
    assert m["cases"] == len(suite["cases"])
    assert m["retrievalHitRate"] >= 0.9 and m["passRate"] >= 0.7


def test_dashboard_reflects_activity(client):
    run_id = start(client, workflow_id(client, "Policy Q&A"), "How many PTO days?")
    wait_for(client, run_id, {"completed"})
    d = client.get("/api/dashboard").json()
    assert d["kpis"]["runs"] >= 1 and d["kpis"]["successRate"] == 100.0 and d["kpis"]["spend"] > 0
    assert {"from": "intake", "to": "researcher", "count": 1} in d["routing"]["edges"]
    researcher = next(a for a in d["agents"] if a["id"] == "researcher")
    assert researcher["calls"] >= 2
    assert d["recentRuns"][0]["id"] == run_id
    assert client.get("/api/runs/not-a-run").status_code == 404
    assert client.post("/api/approvals/nope/decide", json={"approved": True}).status_code == 404
