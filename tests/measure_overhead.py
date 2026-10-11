"""Bounded local cost comparison; no host calls, network, tokens or prices."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("progress_server", ROOT / "plugins/progress-panel/server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def wire_bytes(value):
    return len((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))


def fields():
    stages = [{"id": name, "title": title, "status": "running" if index == 0 else "pending",
        "actor": "Root agent", "detail": detail}
        for index, (name, title, detail) in enumerate([
            ("inspect", "Inspect the current contracts", "Read the affected sources and identify acceptance checks."),
            ("build", "Implement the candidate", "Coordinate API, UI, documentation and test workers."),
            ("verify", "Run local verification", "Check protocol, persistence, bridge and distribution behavior."),
            ("review", "Review the changed boundaries", "Check capability isolation, compatibility and finalization."),
            ("prepare", "Prepare the local candidate", "Record results and retain the native acceptance gap."),
            ("report", "Report confirmed results", "Explain changes, measured costs and remaining limitations.")])]
    stages[1]["agents"] = [{"id": name, "actor": actor, "status": "pending", "detail": detail}
        for name, actor, detail in [("api", "API worker", "Validate patches and revisions."),
            ("ui", "UI worker", "Render freshness and nested agents."),
            ("docs", "Docs worker", "Document lifecycle and compatibility."),
            ("tests", "Test worker", "Check the affected persistence contracts.")]]
    return {"title": "Prepare a reliable progress panel candidate", "actor": "Root agent",
        "current": stages[0]["title"], "blocker": "", "stages": stages}


def milestones():
    initial = fields()
    changes = []
    for index in range(1, 6):
        patch = {"current": initial["stages"][index]["title"], "stages": [
            {"id": initial["stages"][index - 1]["id"], "status": "completed"},
            {"id": initial["stages"][index]["id"], "status": "running"}]}
        if index == 1:
            agents = copy.deepcopy(initial["stages"][1]["agents"])
            for agent in agents:
                agent["status"] = "running"
            patch["stages"][1]["agents"] = agents
        if index == 2:
            agents = copy.deepcopy(initial["stages"][1]["agents"])
            for agent in agents:
                agent["status"] = "completed"
                agent["detail"] = "Assigned work complete; root verification remains."
            patch["stages"][0]["agents"] = agents
        changes.append(patch)
        if index == 1:
            agents = copy.deepcopy(patch["stages"][1]["agents"])
            agents[2]["status"] = "completed"
            agents[2]["detail"] = "Draft complete; implementation remains in progress."
            changes.append({"stages": [{"id": "build", "agents": agents}]})
    return changes


def measure(mode, directory):
    store = server.Store(directory)
    app = server.Server(store)
    app.initialized = app.ready = True  # Exclude discovery/initialization in both modes.
    sql_counts = {"INSERT": 0, "UPDATE": 0, "DELETE": 0}

    def observe(sql):
        first = sql.lstrip().split(" ", 1)[0].upper()
        if first in sql_counts:
            sql_counts[first] += 1

    store.db.set_trace_callback(observe)  # Count only; never retain expanded SQL or capabilities.
    totals = {"calls": 0, "request_bytes": 0, "response_bytes": 0}

    def call(name, arguments):
        totals["calls"] += 1
        request = {"jsonrpc": "2.0", "id": totals["calls"], "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}
        totals["request_bytes"] += wire_bytes(request)
        reply = app.dispatch(request)
        totals["response_bytes"] += wire_bytes(reply)
        assert "error" not in reply and not reply["result"].get("isError"), "Measured tool failed"
        return reply["result"]["structuredContent"]

    started = time.perf_counter()
    task_id = "typical-execution"
    created = call("create_progress", {"task_id": task_id, **fields()})
    state = created["state"]
    call("open_progress_panel", {"task_id": task_id, "read_token": created["read_token"]})
    for patch in milestones():
        args = {"task_id": task_id, "write_token": created["write_token"], "expected_revision": state["revision"]}
        proposed = server.merge_patch(state, patch)
        args.update({"patch": patch} if mode == "patch" else proposed)
        state = call("update_progress", args)["state"]
        assert {key: state[key] for key in proposed} == proposed
    final_fields = server.merge_patch(state, {"current": "Local candidate checked; native acceptance remains.",
        "stages": [{"id": "report", "status": "completed"}]})
    state = call("finish_progress", {"task_id": task_id, "write_token": created["write_token"],
        "expected_revision": state["revision"], **final_fields})["state"]
    totals["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    totals.update(sql_mutations=sql_counts, changed_rows=store.db.total_changes,
        retained_rows=store.db.execute("SELECT count(*) FROM tasks").fetchone()[0],
        final_revision=state["revision"], stored_state_bytes=store.db.execute(
            "SELECT length(CAST(state AS BLOB)) FROM tasks WHERE id=?", (task_id,)).fetchone()[0])
    store.close()
    totals["database_file_bytes"] = (directory / "progress.sqlite3").stat().st_size
    return totals, final_fields


def measure_reconciliation(kind, directory):
    """Compare one ordinary full write with one structural or semantic write."""
    store = server.Store(directory)
    app = server.Server(store)
    app.initialized = app.ready = True
    totals = {"calls": 0, "request_bytes": 0, "response_bytes": 0}
    operations = {name: 0 for name in ("BEGIN", "SELECT", "INSERT", "UPDATE", "DELETE", "COMMIT", "ROLLBACK")}
    def observe(sql):
        name = sql.lstrip().split(" ", 1)[0].upper()
        if name in operations:
            operations[name] += 1
    store.db.set_trace_callback(observe)
    def call(name, arguments):
        totals["calls"] += 1
        request = {"jsonrpc": "2.0", "id": totals["calls"], "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        totals["request_bytes"] += wire_bytes(request)
        response = app.dispatch(request)
        totals["response_bytes"] += wire_bytes(response)
        assert not response.get("error") and not response["result"].get("isError"), "Reconciliation measurement failed"
        return response["result"]["structuredContent"]
    initial = fields()
    initial["stages"][0]["status"] = "completed"
    created = call("create_progress", {"task_id": "reconciliation", **initial})
    state = created["state"]
    args = {"task_id": "reconciliation", "write_token": created["write_token"], "expected_revision": state["revision"]}
    if kind == "affected_agents":
        state = call("update_progress", {**args, "patch": {"stages": [{"id": "build", "agents": [
            {**agent, "status": "cancelled", "detail": "Cancellation confirmed"} for agent in state["stages"][1]["agents"]]}]}})["state"]
        args["expected_revision"] = state["revision"]
    proposed = {key: copy.deepcopy(state[key]) for key in ("title", "actor", "current", "blocker", "stages")}
    proposed["current"] = "Continue the latest authorized scope."
    if kind == "semantic_patch":
        arguments = {"patch": {"current": proposed["current"]}, "plan_change": {"summary": "User refined verification."}}
    else:
        if kind != "ordinary_full":
            index = 1 if kind == "affected_agents" else 0
            proposed["stages"].pop(index)
            proposed["stages"].append({"id": "new-check", "title": "Check the new requirement", "status": "pending"})
        arguments = proposed
        if kind in ("structural_summary", "affected_agents"):
            arguments["plan_change"] = {"summary": "User added a check and removed prior work."}
    before = dict(operations)
    request_before, response_before = totals["request_bytes"], totals["response_bytes"]
    state = call("update_progress", {**args, **arguments})["state"]
    totals.update(write_request_bytes=totals["request_bytes"] - request_before,
        write_response_bytes=totals["response_bytes"] - response_before,
        write_sql_operations={key: operations[key] - before[key] for key in operations},
        all_sql_operations=operations, stored_state_bytes=len(server.serialized_state(state).encode("utf-8")),
        plan_metadata_bytes=wire_bytes(state["plan"]) - 1 if "plan" in state else 0,
        retained_rows=store.db.execute("SELECT count(*) FROM tasks").fetchone()[0])
    store.close()
    return totals


if __name__ == "__main__":
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="progress-cost-") as temporary:
        root = Path(temporary).resolve()
        full, full_state = measure("full", root / "full")
        patch, patch_state = measure("patch", root / "patch")
        assert full_state == patch_state, "Compared final snapshots differ"
        assert full["calls"] == patch["calls"] == 9
        assert full["sql_mutations"] == patch["sql_mutations"] == {"INSERT": 1, "UPDATE": 7, "DELETE": 0}
        reconciliation = {kind: measure_reconciliation(kind, root / kind) for kind in
            ("ordinary_full", "structural_auto", "structural_summary", "semantic_patch", "affected_agents")}
        assert all(item["write_sql_operations"] == {"BEGIN": 1, "SELECT": 1, "INSERT": 0, "UPDATE": 1,
            "DELETE": 0, "COMMIT": 1, "ROLLBACK": 0} for item in reconciliation.values())
        print(json.dumps({"scenario": "six stages, four agents, six milestone updates, create/open/finish",
            "scope": "in-process dispatch + serialization + local SQLite; excludes host, startup, UI polls and transport latency",
            "full": full, "patch": patch, "reconciliation": reconciliation}, ensure_ascii=False, indent=2))
