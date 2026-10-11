"""Bounded real stdio, SQLite restart and authorization tests. No sockets."""
import json
import copy
import importlib.util
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "plugins/progress-panel/server.py"
SERVER_SPEC = importlib.util.spec_from_file_location("progress_server", SERVER)
progress_server = importlib.util.module_from_spec(SERVER_SPEC)
SERVER_SPEC.loader.exec_module(progress_server)


def assert_schema(value, spec):
    """Validate the declared JSON Schema subset against actual protocol output."""
    if "not" in spec:
        try:
            assert_schema(value, spec["not"])
        except AssertionError:
            pass
        else:
            raise AssertionError("Value matches excluded schema")
    if "anyOf" in spec:
        matched = False
        for choice in spec["anyOf"]:
            try:
                assert_schema(value, choice)
                matched = True
            except AssertionError:
                pass
        assert matched, "Value must match at least one schema alternative"
    if "oneOf" in spec:
        matches = 0
        for choice in spec["oneOf"]:
            try:
                assert_schema(value, choice)
                matches += 1
            except AssertionError:
                pass
        assert matches == 1, "Output must match exactly one schema alternative"
    if "required" in spec:
        assert isinstance(value, dict)
        assert set(spec["required"]) <= set(value)
    kind = spec.get("type")
    if kind is None:
        return
    if kind == "null":
        assert value is None
    elif kind == "object":
        assert isinstance(value, dict)
        assert set(spec.get("required", [])) <= set(value)
        if spec.get("additionalProperties") is False:
            assert set(value) <= set(spec["properties"])
        for key, item in value.items():
            assert_schema(item, spec["properties"][key])
    elif kind == "array":
        assert isinstance(value, list)
        assert spec.get("minItems", 0) <= len(value) <= spec.get("maxItems", float("inf"))
        for item in value:
            assert_schema(item, spec["items"])
    elif kind == "string":
        assert isinstance(value, str)
        assert spec.get("minLength", 0) <= len(value) <= spec.get("maxLength", float("inf"))
        if "pattern" in spec:
            assert re.fullmatch(spec["pattern"], value)
        if "enum" in spec:
            assert value in spec["enum"]
        if spec.get("format") == "date-time":
            from datetime import datetime
            assert datetime.fromisoformat(value).tzinfo is not None
    elif kind == "boolean":
        assert type(value) is bool
    elif kind == "integer":
        assert type(value) is int
        assert spec.get("minimum", -float("inf")) <= value <= spec.get("maximum", float("inf"))
    else:
        raise AssertionError("Unsupported output schema type: " + kind)


class Client:
    def __init__(self, data, extra_args=()):
        self.process = subprocess.Popen([sys.executable, "-B", str(SERVER), "--data-dir", str(data), *extra_args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.next_id = 1
        self.tool_calls = []
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def send(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode())
        self.process.stdin.flush()

    def receive(self, timeout=4):
        if not self.selector.select(timeout):
            raise AssertionError("Stdio server did not respond within %s seconds" % timeout)
        return json.loads(self.process.stdout.readline())

    def request(self, method, params=None, timeout=4):
        ident = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        reply = self.receive(timeout)
        if reply.get("id") != ident:
            raise AssertionError("Incorrect request correlation")
        return reply

    def initialize(self):
        reply = self.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {"extensions": {"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}}}, "clientInfo": {"name": "test", "version": "1"}})
        assert reply["result"]["protocolVersion"] == "2025-11-25"
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.tool_schemas = {t["name"]: t["outputSchema"] for t in self.request("tools/list")["result"]["tools"]}

    def call(self, name, arguments):
        self.tool_calls.append(name)
        result = self.request("tools/call", {"name": name, "arguments": arguments})["result"]
        if not result.get("isError"):
            assert_schema(result["structuredContent"], self.tool_schemas[name])
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=4)
        self.selector.close()
        if not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="protocol-", )
        self.data = Path(self.temp.name).resolve() / "private-data"
        self.clients = []
        self.client = self.start()

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.temp.cleanup()

    def start(self, extra_args=()):
        client = Client(self.data, extra_args)
        self.clients.append(client)
        client.initialize()
        return client

    def fields(self):
        return {"title": "Проверка панели", "actor": "Основной агент", "current": "Реализация",
            "stages": [{"id": "build", "title": "Собрать", "status": "running"},
                       {"id": "verify", "title": "Проверить", "status": "pending"}]}

    def create(self, ident="task-test"):
        reply = self.client.call("create_progress", {"task_id": ident, **self.fields()})
        self.assertNotIn("isError", reply)
        return reply["structuredContent"]

    def agents(self):
        return [{"id": "agent-" + str(i), "actor": "Worker " + str(i), "status": status,
            "detail": "Actual work " + str(i)} for i, status in enumerate(("running", "completed", "pending", "blocked"))]

    def read(self, created, ident="task-test"):
        return self.client.call("get_progress", {"task_id": ident,
            "read_token": created["read_token"]})["structuredContent"]["state"]

    def test_patch_preserves_order_and_omissions_and_clears_explicit_fields(self):
        created = self.create()
        args = {"task_id": "task-test", "write_token": created["write_token"], "expected_revision": 1}
        first = self.client.call("update_progress", {**args, "patch": {"stages": [
            {"id": "verify", "detail": "Verification pending"}, {"id": "build", "agents": self.agents()}]}})["structuredContent"]["state"]
        self.assertEqual(first["revision"], 2)
        self.assertEqual([s["id"] for s in first["stages"]], ["build", "verify"])
        self.assertEqual(first["stages"][0]["status"], "running")
        self.assertEqual(first["stages"][0]["agents"], self.agents())
        self.assertEqual(first["actor"], created["state"]["actor"])
        self.assertNotIn("agents", first["stages"][1])
        second = self.client.call("update_progress", {**args, "expected_revision": 2,
            "patch": {"actor": "", "current": "", "stages": [{"id": "build", "agents": []}]}})["structuredContent"]["state"]
        self.assertEqual(second["stages"][0]["agents"], [])
        self.assertEqual(second["actor"], "")
        self.assertEqual(second["current"], "")
        self.assertEqual(second["stages"][1], first["stages"][1])
        completed = [{**agent, "status": "completed"} for agent in self.agents()]
        third = self.client.call("update_progress", {**args, "expected_revision": 3,
            "patch": {"stages": [{"id": "build", "agents": completed}]}})["structuredContent"]["state"]
        self.assertEqual(third["stages"][0]["status"], "running")
        self.assertFalse(third["finalized"])

    def test_patch_auth_schema_merge_failures_leave_exact_stored_state(self):
        import sqlite3
        created = self.create()
        args = {"task_id": "task-test", "write_token": created["write_token"], "expected_revision": 1}
        malformed = [None, [], "patch", {"unknown": 1}, {"title": ""}, {"actor": None},
            {"stages": {}}, {"stages": [{"title": "Missing id"}]}, {"stages": [{"id": "new"}]},
            {"stages": [{"id": "build"}, {"id": "build"}]}, {"stages": [{"id": "build", "unknown": 1}]},
            {"stages": [{"id": "build", "status": "blocked"}]}, {"stages": [{"id": "build", "status": False}]},
            {"stages": [{"id": "build", "detail": "\ud800"}]}, {"stages": [{"id": "build", "actor": "x" * 161}]}]
        with sqlite3.connect(str(self.data / "progress.sqlite3")) as db:
            raw = db.execute("SELECT revision,state FROM tasks").fetchone()
        for patch in malformed:
            with self.subTest(patch=patch):
                self.assertTrue(self.client.call("update_progress", {**args, "patch": patch})["isError"])
        for capability in (created["read_token"], "0" * 64):
            self.assertTrue(self.client.call("update_progress", {**args, "write_token": capability, "patch": {"current": "Denied"}})["isError"])
        self.assertTrue(self.client.call("update_progress", {**args, "expected_revision": True, "patch": {}})["isError"])
        self.assertTrue(self.client.call("update_progress", {**args, "expected_revision": 2, "patch": {}})["isError"])
        self.assertTrue(self.client.call("update_progress", {**args, "patch": {}, **self.fields()})["isError"])
        self.assertTrue(self.client.call("finish_progress", {**args, "patch": {}})["isError"])
        with sqlite3.connect(str(self.data / "progress.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT revision,state FROM tasks").fetchone(), raw)
        fixed = self.client.call("update_progress", {**args, "patch": {"blocker": "Await check",
            "stages": [{"id": "build", "status": "blocked"}]}})["structuredContent"]["state"]
        self.assertEqual(fixed["revision"], 2)
        self.assertTrue(self.client.call("update_progress", {**args, "expected_revision": 2,
            "patch": {"blocker": ""}})["isError"])
        self.assertEqual(self.read(created), fixed)

    def test_agents_strict_limits_unicode_and_duplicate_identity_across_stages(self):
        fields = self.fields()
        fields["stages"][0]["agents"] = [{"id": "build", "actor": "😀" * 160,
            "status": "running", "detail": "😀" * 600}]
        created = self.client.call("create_progress", {"task_id": "task-test", **fields})["structuredContent"]
        self.assertEqual(created["state"]["stages"][0]["agents"], fields["stages"][0]["agents"])
        malformed = [None, {}, self.agents() * 3, [{"id": "same", "actor": "A", "status": "running"}] * 2,
            [{"id": "../escape", "actor": "A", "status": "running"}], [{"id": "a", "status": "running"}],
            [{"id": "a", "actor": " ", "status": "running"}], [{"id": "a", "actor": 4, "status": "running"}],
            [{"id": "a", "actor": "A", "status": []}], [{"id": "a", "actor": "A", "status": "stale"}],
            [{"id": "a", "actor": "😀" * 161, "status": "running"}],
            [{"id": "a", "actor": "A", "status": "running", "detail": "😀" * 601}],
            [{"id": "a", "actor": "A\x00", "status": "running"}],
            [{"id": "a", "actor": "A", "status": "running", "detail": "\ud800"}],
            [{"id": "a", "actor": "A", "status": "running", "write_token": "untrusted"}]]
        args = {"task_id": "task-test", "write_token": created["write_token"], "expected_revision": 1}
        for agents in malformed:
            with self.subTest(agents=agents):
                self.assertTrue(self.client.call("update_progress", {**args,
                    "patch": {"stages": [{"id": "build", "agents": agents}]}})["isError"])
        duplicate = self.client.call("update_progress", {**args,
            "patch": {"stages": [{"id": "verify", "agents": [{"id": "build", "actor": "B", "status": "pending"}]}]}})
        self.assertTrue(duplicate["isError"])
        self.assertEqual(self.read(created), created["state"])
        maximum = [{"id": "agent-" + str(i), "actor": "A", "status": "pending"} for i in range(8)]
        accepted = self.client.call("update_progress", {**args, "patch": {"stages": [{"id": "build", "agents": maximum}]}})
        self.assertEqual(len(accepted["structuredContent"]["state"]["stages"][0]["agents"]), 8)

    def test_patch_input_schema_declares_mutually_exclusive_modes(self):
        spec = next(t for t in self.client.request("tools/list")["result"]["tools"] if t["name"] == "update_progress")["inputSchema"]
        base = {"task_id": "task-test", "write_token": "a" * 64, "expected_revision": 1}
        for args in ({**base, **self.fields()}, {**base, "patch": {}},
                     {**base, "patch": {"stages": [{"id": "build", "agents": self.agents()}]}}):
            assert_schema(args, spec)
        for args in (base, {**base, **self.fields(), "patch": {}}, {**base, "patch": {}, "actor": "mixed"},
                     {**base, "patch": {"unknown": 1}}, {**base, "patch": {"stages": [{"title": "no id"}]}}):
            with self.assertRaises(AssertionError):
                assert_schema(args, spec)

    def test_concurrent_patch_cas_uses_real_sqlite_and_preserves_other_stage(self):
        import concurrent.futures
        import threading
        created = self.create()
        other = self.start()
        barrier = threading.Barrier(2)
        def write(client, marker):
            barrier.wait(timeout=3)
            return client.call("update_progress", {"task_id": "task-test", "write_token": created["write_token"],
                "expected_revision": 1, "patch": {"current": marker,
                "stages": [{"id": "build", "detail": marker, "agents": self.agents()}]}})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, client, marker) for client, marker in ((self.client, "writer-a"), (other, "writer-b"))]
            replies = [future.result(timeout=5) for future in futures]
        self.assertEqual(sum(not reply.get("isError", False) for reply in replies), 1)
        loser = next(reply for reply in replies if reply.get("isError"))
        self.assertIn("Stale revision", loser["content"][0]["text"])
        state = self.read(created)
        self.assertEqual(state["revision"], 2)
        self.assertEqual(state["stages"][0]["detail"], state["current"])
        self.assertEqual(state["stages"][1], created["state"]["stages"][1])
        self.assertEqual(len(state["stages"][0]["agents"]), 4)

    def test_interruption_before_finish_retains_aggregate_and_old_widget_capability(self):
        created = self.create()
        opening = {"task_id": "task-test", "read_token": created["read_token"]}
        self.client.call("open_progress_panel", opening)
        expected = self.client.call("update_progress", {"task_id": "task-test", "write_token": created["write_token"],
            "expected_revision": 1, "patch": {"stages": [{"id": "build", "agents": self.agents()}]}})["structuredContent"]["state"]
        self.client.process.terminate()
        self.client.process.wait(timeout=4)
        self.client.close()
        self.client = self.start()
        read = self.client.call("get_progress", opening)
        self.assertEqual(read["structuredContent"]["state"], expected)
        self.assertFalse(expected["finalized"])
        self.assertIsNone(expected["finalized_at"])
        self.assertNotIn(created["write_token"], json.dumps(read))
        final = self.client.call("finish_progress", {"task_id": "task-test", "write_token": created["write_token"],
            "expected_revision": 2, **{key: expected[key] for key in ("title", "stages", "actor", "current", "blocker")}})["structuredContent"]["state"]
        denied = self.client.call("update_progress", {"task_id": "task-test", "write_token": created["write_token"],
            "expected_revision": 3, "patch": {"current": "Denied after finish"}})
        self.assertTrue(denied["isError"])
        self.assertEqual(self.read(created), final)

    def test_complete_merged_snapshot_byte_bound_and_single_sql_update(self):
        store = progress_server.Store(self.data)
        self.addCleanup(store.close)
        fields = {"title": "Bounded", "stages": [{"id": "s-" + str(i), "title": "S", "status": "running",
            "detail": "x" * 600} for i in range(32)]}
        created = store.create({"task_id": "size-test", **fields})
        args = {"task_id": "size-test", "write_token": created["write_token"], "expected_revision": 1}
        traces = []
        store.db.set_trace_callback(traces.append)
        agents = [{"id": "a-" + str(i), "actor": "A", "status": "running", "detail": "x" * 600} for i in range(8)]
        for index in range(16):
            patch_agents = [{**agent, "id": "s" + str(index) + "-" + agent["id"]} for agent in agents]
            before = store.db.execute("SELECT revision,state FROM tasks WHERE id='size-test'").fetchone()
            update_count = sum(query.startswith("UPDATE tasks ") for query in traces)
            try:
                result = store.update({**args, "patch": {"stages": [{"id": "s-" + str(index), "agents": patch_agents}]}})
            except progress_server.Invalid as exc:
                self.assertIn("Snapshot exceeds 64 KiB", str(exc))
                self.assertEqual(store.db.execute("SELECT revision,state FROM tasks WHERE id='size-test'").fetchone(), before)
                self.assertEqual(sum(query.startswith("UPDATE tasks ") for query in traces), update_count)
                break
            self.assertEqual(sum(query.startswith("UPDATE tasks ") for query in traces), update_count + 1)
            args["expected_revision"] = result["state"]["revision"]
        else:
            self.fail("Merged snapshots did not reach the size bound")
        oversized = copy.deepcopy(fields)
        for index, stage in enumerate(oversized["stages"]):
            stage["agents"] = [{**agent, "id": str(index) + "-" + agent["id"]} for agent in agents]
        for method in (store.update, store.finish):
            with self.assertRaisesRegex(progress_server.Invalid, "Snapshot exceeds 64 KiB"):
                method({**args, **oversized})
            self.assertEqual(store.db.execute("SELECT revision,state FROM tasks WHERE id='size-test'").fetchone(), before)
        with self.assertRaisesRegex(progress_server.Invalid, "Snapshot exceeds 64 KiB"):
            store.create({"task_id": "too-large", **oversized})
        unicode_fields = copy.deepcopy(fields)
        for stage in unicode_fields["stages"]:
            stage["detail"] = "😀" * 600
        # Character limits alone do not bound the UTF-8 state written to SQLite.
        with self.assertRaisesRegex(progress_server.Invalid, "Snapshot exceeds 64 KiB"):
            store.create({"task_id": "unicode-too-large", **unicode_fields})
        self.assertEqual(store.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 1)
        # Old snapshots remain readable without introducing a new read limit or rewrite.
        legacy = progress_server.snapshot_fields(oversized)
        legacy.update(task_id="size-test", revision=args["expected_revision"], updated_at=created["state"]["updated_at"])
        encoded = json.dumps(legacy, ensure_ascii=False)
        self.assertGreater(len(encoded.encode("utf-8")), progress_server.MAX_SNAPSHOT_BYTES)
        store.db.execute("UPDATE tasks SET state=? WHERE id='size-test'", (encoded,))
        state, _ = store.authenticated("size-test", created["read_token"])
        self.assertFalse(state["finalized"])
        self.assertEqual(store.db.execute("SELECT state FROM tasks WHERE id='size-test'").fetchone()[0], encoded)

    def test_storage_capacity_concurrent_create_preserves_read_update_and_finish(self):
        import concurrent.futures
        import threading
        import sqlite3
        first = self.create("retained")
        for index in range(126):
            self.create("retained-" + str(index))
        other = self.start()
        barrier = threading.Barrier(2)
        def create_last(client, ident):
            barrier.wait(timeout=3)
            return client.call("create_progress", {"task_id": ident, **self.fields()})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create_last, client, ident) for client, ident in ((self.client, "last-a"), (other, "last-b"))]
            replies = [future.result(timeout=5) for future in futures]
        self.assertEqual(sum(not reply.get("isError", False) for reply in replies), 1)
        denied = self.client.call("create_progress", {"task_id": "over-capacity", **self.fields()})
        self.assertTrue(denied["isError"])
        self.assertIn("128 retained executions", denied["content"][0]["text"])
        with sqlite3.connect(str(self.data / "progress.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 128)
        self.assertEqual(self.read(first, "retained"), first["state"])
        args = {"task_id": "retained", "write_token": first["write_token"], "expected_revision": 1}
        self.assertEqual(self.client.call("update_progress", {**args, "patch": {"current": "Still writable"}})["structuredContent"]["state"]["revision"], 2)
        final = self.client.call("finish_progress", {**args, "expected_revision": 2, **self.fields()})["structuredContent"]["state"]
        self.assertTrue(final["finalized"])
        with sqlite3.connect(str(self.data / "progress.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 128)

    def test_language_default_configuration_override_and_read_once_preserve_state(self):
        def language(client):
            resource = client.request("resources/read", {"uri": "ui://progress/panel.html"})["result"]["contents"][0]
            title = client.request("resources/list")["result"]["resources"][0]["title"]
            return resource["text"], title
        default_html, title = language(self.client)
        self.assertIn('<html lang="en">', default_html)
        self.assertEqual(title, "Task stages")
        created = self.create()
        args = {"task_id": "task-test", "write_token": created["write_token"], "expected_revision": 1, **self.fields()}
        final = self.client.call("finish_progress", args)["structuredContent"]["state"]
        import sqlite3
        with sqlite3.connect(str(self.data / "progress.sqlite3")) as db:
            stored = db.execute("SELECT state FROM tasks").fetchone()[0]
        config = self.data / "config.json"
        config.write_text('{"language":"ru"}')
        config.chmod(0o600)
        russian = self.start()
        russian_html, title = language(russian)
        self.assertIn('<html lang="ru">', russian_html)
        self.assertEqual(title, "Этапы задачи")
        self.assertEqual(language(self.client), (default_html, "Task stages"))
        config.write_text('{"language":"en"}')
        self.assertEqual(language(russian), (russian_html, "Этапы задачи"))
        self.assertIn('<html lang="en">', language(self.start())[0])
        config.write_text('{"language":"ru"}')
        self.assertIn('<html lang="en">', language(self.start(("--language", "en")))[0])
        config.write_text('invalid config skipped by an explicit override')
        self.assertIn('<html lang="ru">', language(self.start(("--language", "ru")))[0])
        for client in (self.client, russian):
            self.assertEqual(client.call("get_progress", {"task_id": "task-test", "read_token": created["read_token"]})["structuredContent"]["state"], final)
        with sqlite3.connect(str(self.data / "progress.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT state FROM tasks").fetchone()[0], stored)

    def test_invalid_language_configuration_fails_before_sqlite_open(self):
        invalid = [b'{"language":"fr"}', b'{"language":true}', b'{"language":null}', b'{"language":[]}', b'[]', b'{}',
                   b'{"language":"en","extra":1}', b'{"language":"en","language":"ru"}', b'{"language":NaN}',
                   b'\xff', b'{', b' ' * 1025]
        for index, content in enumerate(invalid):
            data = Path(self.temp.name).resolve() / ("invalid-" + str(index))
            data.mkdir(mode=0o700)
            config = data / "config.json"
            config.write_bytes(content); config.chmod(0o600)
            result = subprocess.run([sys.executable, "-B", str(SERVER), "--data-dir", str(data)], input=b"", capture_output=True, timeout=4)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"invalid config.json", result.stderr)
            self.assertFalse((data / "progress.sqlite3").exists())
            self.assertEqual(config.read_bytes(), content)
        data = Path(self.temp.name).resolve() / "invalid-cli"
        result = subprocess.run([sys.executable, "-B", str(SERVER), "--data-dir", str(data), "--language", "fr"], input=b"", capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 2); self.assertEqual(result.stdout, b"")
        self.assertFalse(data.exists())

    def test_unsafe_language_configuration_is_rejected_without_opening_sqlite(self):
        target = Path(self.temp.name).resolve() / "configuration-target"
        target.write_text('{"language":"ru"}'); target.chmod(0o600)
        for kind in ("symlink", "directory", "fifo", "public", "hardlink"):
            data = Path(self.temp.name).resolve() / kind
            data.mkdir(mode=0o700)
            config = data / "config.json"
            if kind == "symlink": config.symlink_to(target)
            elif kind == "directory": config.mkdir()
            elif kind == "fifo": os.mkfifo(config, 0o600)
            elif kind == "hardlink": os.link(target, config)
            else: config.write_text('{"language":"ru"}'); config.chmod(0o644)
            result = subprocess.run([sys.executable, "-B", str(SERVER), "--data-dir", str(data)], input=b"", capture_output=True, timeout=4)
            self.assertEqual(result.returncode, 1, kind)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"invalid config.json", result.stderr)
            self.assertFalse((data / "progress.sqlite3").exists())
        self.assertEqual(target.read_text(), '{"language":"ru"}')

    def test_initialize_accepts_optional_protocol_metadata(self):
        client = Client(self.data)
        self.clients.append(client)
        params = {"protocolVersion": "2025-11-25", "capabilities": {},
                  "clientInfo": {"name": "test", "version": "1"},
                  "_meta": {"openai/locale": "ru-RU", "progressToken": "handshake",
                            "example.com/context": {"hint": "untrusted"}}}
        reply = client.request("initialize", params)
        self.assertIn("result", reply, reply)
        self.assertEqual(reply["result"]["protocolVersion"], "2025-11-25")
        self.assertNotIn("_meta", reply["result"])
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized",
                     "params": {"_meta": {"example.com/context": "ready"}}})
        self.assertEqual(len(client.request("tools/list")["result"]["tools"]), 5)

    def test_discovery_and_resource_read_accept_protocol_metadata(self):
        meta = {"openai/locale": "ru-RU", "progressToken": 0,
                "example.com/context": {"hint": "ignored"}}
        for method, field, count in [("tools/list", "tools", 5),
                                     ("resources/list", "resources", 1),
                                     ("resources/templates/list", "resourceTemplates", 0)]:
            with self.subTest(method=method):
                expected = self.client.request(method)["result"]
                reply = self.client.request(method, {"_meta": meta})
                self.assertIn("result", reply, reply)
                result = reply["result"]
                self.assertEqual(result, expected)
                self.assertEqual(len(result[field]), count)
                self.assertNotIn("nextCursor", result)
        resource = self.client.request("resources/list")["result"]["resources"][0]
        content = self.client.request("resources/read", {"uri": resource["uri"], "_meta": meta})
        self.assertIn("result", content, content)
        self.assertEqual(content["result"], self.client.request("resources/read", {"uri": resource["uri"]})["result"])
        self.assertEqual(self.client.request("ping", {"_meta": meta})["result"], {})

    def test_single_page_discovery_rejects_unissued_cursors(self):
        for method in ("tools/list", "resources/list", "resources/templates/list"):
            self.assertNotIn("nextCursor", self.client.request(method)["result"])
            for cursor in ("", "unissued-next-page", None, 0, {}, []):
                with self.subTest(method=method, cursor=cursor):
                    reply = self.client.request(method, {"cursor": cursor, "_meta": {}})
                    self.assertEqual(reply["error"]["code"], -32602)
            self.assertIn("result", self.client.request(method, {"_meta": {}}))

    def test_protocol_metadata_does_not_relax_task_or_capability_validation(self):
        created = self.create()
        args = {"task_id": "task-test", "read_token": created["read_token"]}
        meta = {"openai/locale": "ru-RU", "openai/userLocation": {"city": "test"},
                "write_token": created["write_token"], "progressToken": 1.5}
        params = {"name": "get_progress", "arguments": args, "_meta": meta}
        reply = self.client.request("tools/call", params)["result"]
        self.assertNotIn("isError", reply)
        self.assertNotIn(created["write_token"], json.dumps(reply))
        self.assertNotIn("openai/locale", json.dumps(reply))
        for extra in ({"_meta": {}}, {"unknown": "ignored?"}, {"write_token": created["write_token"]}):
            reply = self.client.request("tools/call", {**params, "arguments": {**args, **extra}})["result"]
            self.assertTrue(reply["isError"])
        wrong_read = {"task_id": "task-test", "read_token": "0" * 64}
        self.assertTrue(self.client.request("tools/call", {**params, "arguments": wrong_read})["result"]["isError"])
        wrong_write = {"task_id": "task-test", "write_token": created["read_token"],
                       "expected_revision": 1, **self.fields()}
        self.assertTrue(self.client.request("tools/call", {"name": "update_progress", "arguments": wrong_write, "_meta": meta})["result"]["isError"])
        self.assertEqual(self.client.call("get_progress", args)["structuredContent"]["state"]["revision"], 1)

    def test_malformed_protocol_metadata_is_rejected_before_operation(self):
        for method, params in [("ping", {}), ("tools/list", {}), ("resources/list", {}),
                               ("resources/templates/list", {}),
                               ("resources/read", {"uri": "ui://progress/panel.html"}),
                               ("tools/call", {"name": "open_progress_panel", "arguments": {}})]:
            for meta in (None, [], "ru-RU", 1, {"progressToken": True}, {"progressToken": None}, {"progressToken": {}}):
                with self.subTest(method=method, meta=meta):
                    self.assertEqual(self.client.request(method, {**params, "_meta": meta})["error"]["code"], -32602)
            self.assertEqual(self.client.request(method, {**params, "unexpected": 1})["error"]["code"], -32602)
        client = Client(self.data)
        self.clients.append(client)
        base = {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}
        self.assertEqual(client.request("initialize", {**base, "_meta": []})["error"]["code"], -32602)
        self.assertIn("result", client.request("initialize", {**base, "_meta": {}}))
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {"_meta": []}})
        self.assertEqual(client.request("tools/list")["error"]["code"], -32602)
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {"_meta": {}}})
        self.assertIn("result", client.request("tools/list"))

    def test_roundtrip_resources_update_and_restart(self):
        tools = self.client.request("tools/list")["result"]["tools"]
        self.assertEqual({x["name"] for x in tools}, {"create_progress", "open_progress_panel", "update_progress", "finish_progress", "get_progress"})
        opener = next(x for x in tools if x["name"] == "open_progress_panel")
        self.assertNotIn("openai/ui", opener["_meta"])
        self.assertEqual(opener["_meta"]["ui"]["resourceUri"], "ui://progress/panel.html")
        resource = self.client.request("resources/list")["result"]["resources"][0]
        content = self.client.request("resources/read", {"uri": resource["uri"]})["result"]["contents"][0]
        self.assertEqual(content["mimeType"], "text/html;profile=mcp-app")
        self.assertIn("<!doctype html>", content["text"])
        created = self.create()
        opened = self.client.call("open_progress_panel", {"task_id": "task-test", "read_token": created["read_token"]})
        self.assertNotIn("write_token", opened["structuredContent"])
        self.assertNotIn(created["write_token"], json.dumps(opened))
        read_token = opened["_meta"]["read_token"]
        fields = self.fields()
        fields["stages"][0]["status"] = "completed"
        fields["stages"][1]["status"] = "running"
        updated = self.client.call("update_progress", {"task_id": "task-test", "write_token": created["write_token"], "expected_revision": 1, **fields})
        self.assertEqual(updated["structuredContent"]["state"]["revision"], 2)
        self.client.close()
        restarted = self.start()
        state = restarted.call("get_progress", {"task_id": "task-test", "read_token": read_token})["structuredContent"]["state"]
        self.assertEqual(state["stages"][0]["status"], "completed")
        self.assertEqual(state["revision"], 2)
        self.assertEqual((self.data / "progress.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_read_capability_cannot_write_or_read_other_task(self):
        a, b = self.create("task-a"), self.create("task-b")
        read = self.client.call("open_progress_panel", {"task_id": "task-a", "read_token": a["read_token"]})["_meta"]["read_token"]
        for name, args in [
            ("get_progress", {"task_id": "task-b", "read_token": read}),
            ("get_progress", {"task_id": "task-a", "read_token": a["write_token"]}),
            ("open_progress_panel", {"task_id": "task-b", "read_token": a["read_token"]}),
            ("open_progress_panel", {"task_id": "task-a", "write_token": a["write_token"]}),
            ("open_progress_panel", {"task_id": "task-a", "read_token": a["write_token"]}),
            ("update_progress", {"task_id": "task-a", "write_token": read, "expected_revision": 1, **self.fields()}),
            ("get_progress", {"task_id": "../task-a", "read_token": read}),
            ("get_progress", {"task_id": "/etc/passwd", "read_token": read})]:
            self.assertTrue(self.client.call(name, args)["isError"])
        self.assertEqual(self.client.call("open_progress_panel", {"task_id": "task-b", "read_token": b["read_token"]})["structuredContent"]["state"]["revision"], 1)

    def test_all_structured_outputs_match_exact_schema_and_opening_is_read_only(self):
        descriptors = self.client.request("tools/list")["result"]["tools"]
        self.assertTrue(all("outputSchema" in item for item in descriptors))
        opener = next(t for t in descriptors if t["name"] == "open_progress_panel")
        reader = next(t for t in descriptors if t["name"] == "get_progress")
        self.assertEqual(reader["_meta"]["ui"]["visibility"], ["model", "app"])
        self.assertNotIn("resourceUri", reader["_meta"]["ui"])
        self.assertTrue(reader["annotations"]["readOnlyHint"])
        self.assertEqual(set(reader["inputSchema"]["properties"]), {"task_id", "read_token"})
        self.assertEqual(set(reader["inputSchema"]["required"]), {"task_id", "read_token"})
        self.assertEqual(set(opener["inputSchema"]["properties"]), {"task_id", "read_token"})
        empty = self.client.call("open_progress_panel", {})
        self.assertEqual(empty["structuredContent"], {"state": None})
        created = self.create()
        self.assertEqual(set(created), {"state", "write_token", "read_token"})
        opening_args = {"task_id": "task-test", "read_token": created["read_token"]}
        opened = self.client.call("open_progress_panel", opening_args)
        self.assertNotIn(created["write_token"], json.dumps({"arguments": opening_args, "result": opened}))
        state = self.client.call("get_progress", opening_args)
        self.assertEqual(state["structuredContent"], opened["structuredContent"])
        self.assertEqual(state["_meta"], {})
        self.assertNotIn(created["write_token"], json.dumps(state))
        with self.assertRaises(AssertionError):
            assert_schema({"state": created["state"], "write_token": created["write_token"]}, opener["outputSchema"])
        with self.assertRaises(AssertionError):
            assert_schema({"state": None}, self.client.tool_schemas["get_progress"])

    def test_astral_unicode_codepoint_limits_for_all_display_fields(self):
        fields_to_check = [(None, "title", 240), (None, "actor", 600), (None, "current", 600),
            (None, "blocker", 600), ("stage", "title", 240), ("stage", "actor", 160), ("stage", "detail", 600)]
        for index, (scope, name, limit) in enumerate(fields_to_check):
            fields = self.fields()
            target = fields["stages"][0] if scope else fields
            target[name] = "😀" * limit
            result = self.client.call("create_progress", {"task_id": "unicode-" + str(index), **fields})
            self.assertNotIn("isError", result)
            state = result["structuredContent"]["state"]
            self.assertEqual((state["stages"][0] if scope else state)[name], "😀" * limit)
            target[name] += "😀"
            rejected = self.client.call("create_progress", {"task_id": "too-long-" + str(index), **fields})
            self.assertTrue(rejected["isError"])

    def test_stale_update_and_finish_recover_by_read_without_reopening(self):
        created = self.create()
        opening = {"task_id": "task-test", "read_token": created["read_token"]}
        self.client.call("open_progress_panel", opening)
        other = self.start()
        args = {"task_id": "task-test", "write_token": created["write_token"], "expected_revision": 1, **self.fields()}
        self.assertEqual(self.client.call("update_progress", args)["structuredContent"]["state"]["revision"], 2)
        for writer, name, expected in ((other, "update_progress", 3), (self.client, "finish_progress", 4)):
            stale = writer.call(name, args)
            self.assertTrue(stale["isError"])
            self.assertIn("Stale revision", stale["content"][0]["text"])
            current = writer.call("get_progress", opening)
            self.assertEqual(current["_meta"], {})
            self.assertNotIn(created["write_token"], json.dumps(current))
            self.assertEqual(current["structuredContent"]["state"]["revision"], expected - 1)
            args["expected_revision"] = current["structuredContent"]["state"]["revision"]
            recovered = writer.call(name, args)["structuredContent"]["state"]
            self.assertEqual(recovered["revision"], expected)
            self.assertEqual(recovered["finalized"], name == "finish_progress")
        self.assertEqual(sum(c.tool_calls.count("open_progress_panel") for c in self.clients), 1)
        self.assertEqual(sum(c.tool_calls.count("get_progress") for c in self.clients), 2)

    def test_bounded_input_and_safe_xss_storage(self):
        xss = '<img src=x onerror="alert(1)"><script>alert(1)</script>'
        fields = self.fields()
        fields["title"] = xss
        created = self.client.call("create_progress", {"task_id": "xss", **fields})["structuredContent"]
        opened = self.client.call("open_progress_panel", {"task_id": "xss", "read_token": created["read_token"]})
        self.assertEqual(opened["structuredContent"]["state"]["title"], xss)
        malformed = [
            {"task_id": "bad", **self.fields(), "title": "x" * 241},
            {"task_id": "bad", **self.fields(), "stages": []},
            {"task_id": "bad", **self.fields(), "stages": self.fields()["stages"] * 17},
            {"task_id": "bad", **self.fields(), "stages": [{"id": "same", "title": "a", "status": "running"}] * 2},
            {"task_id": "bad", **self.fields(), "unknown": "ignored?"},
            {"task_id": "bad", **self.fields(), "title": "\ud800"},
            {"task_id": "bad", **self.fields(), "stages": [{"id": "b", "title": "b", "status": "blocked"}]},
        ]
        for args in malformed:
            self.assertTrue(self.client.call("create_progress", args)["isError"])
        self.assertIn("error", self.client.request("resources/read", {"uri": "file:///etc/passwd"}))
        self.client.process.stdin.write(b'{"jsonrpc":"2.0","id":50,"method":"ping","method":"tools/list"}\n')
        self.client.process.stdin.flush()
        self.assertEqual(self.client.receive()["error"]["code"], -32700)
        self.assertEqual(self.client.request("ping")["result"], {})

    def test_notifications_cannot_mutate(self):
        self.client.send({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "create_progress", "arguments": {"task_id": "notification", **self.fields()}}})
        created = self.create("notification")
        self.assertEqual(created["state"]["revision"], 1)

    def test_protocol_errors_and_oversized_transport(self):
        self.assertEqual(self.client.request("unknown")["error"]["code"], -32601)
        self.assertEqual(self.client.request("tools/call", {"name": "missing"})["error"]["code"], -32602)
        self.client.process.stdin.write(b"x" * 65537 + b"\n")
        self.client.process.stdin.flush()
        self.assertEqual(self.client.receive()["error"]["code"], -32700)
        self.client.process.wait(timeout=4)
        self.assertEqual(self.client.process.returncode, 0)

    def test_finish_is_irrevocable_across_restart_and_next_execution(self):
        first = self.create("execution-a")
        final_fields = self.fields()
        final_fields["stages"][0]["status"] = "blocked"
        final_fields["blocker"] = "Waiting for a required check"
        args = {"task_id": "execution-a", "write_token": first["write_token"], "expected_revision": 1, **final_fields}
        denied = self.client.call("finish_progress", {**args, "write_token": first["read_token"]})
        self.assertTrue(denied["isError"])
        stale = self.client.call("finish_progress", {**args, "expected_revision": 2})
        self.assertTrue(stale["isError"])
        final = self.client.call("finish_progress", args)["structuredContent"]["state"]
        self.assertTrue(final["finalized"])
        self.assertEqual(final["finalized_at"], final["updated_at"])
        self.assertEqual(final["revision"], 2)
        for name in ("update_progress", "finish_progress"):
            self.assertTrue(self.client.call(name, {**args, "expected_revision": 2})["isError"])
        second = self.create("execution-b")
        changed = self.client.call("update_progress", {"task_id": "execution-b", "write_token": second["write_token"], "expected_revision": 1, **self.fields()})
        self.assertFalse(changed["structuredContent"]["state"]["finalized"])
        self.client.close()
        self.client = self.start()
        for name in ("open_progress_panel", "get_progress"):
            self.assertEqual(self.client.call(name, {"task_id": "execution-a", "read_token": first["read_token"]})["structuredContent"]["state"], final)
        self.assertTrue(self.client.call("finish_progress", {**args, "write_token": second["write_token"]})["isError"])

    def test_finish_update_race_uses_one_transaction(self):
        import concurrent.futures
        created = self.create()
        other = self.start()
        args = {"task_id": "task-test", "write_token": created["write_token"], "expected_revision": 1, **self.fields()}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.client.call, "finish_progress", args), pool.submit(other.call, "update_progress", args)]
            replies = [f.result() for f in futures]
        self.assertEqual(sum(not r.get("isError", False) for r in replies), 1)
        state = self.client.call("get_progress", {"task_id": "task-test", "read_token": created["read_token"]})["structuredContent"]["state"]
        self.assertEqual(state["revision"], 2)
        if not state["finalized"]:
            state = self.client.call("finish_progress", {**args, "expected_revision": 2})["structuredContent"]["state"]
        self.assertTrue(state["finalized"])
        self.assertTrue(other.call("update_progress", {**args, "expected_revision": state["revision"]})["isError"])

    def test_legacy_read_does_not_rewrite_state(self):
        import sqlite3
        created = self.create()
        with sqlite3.connect(str(self.data / "progress.sqlite3")) as db:
            raw = db.execute("SELECT state FROM tasks WHERE id='task-test'").fetchone()[0]
            legacy = json.loads(raw)
            legacy.pop("finalized"); legacy.pop("finalized_at")
            raw = json.dumps(legacy)
            db.execute("UPDATE tasks SET state=? WHERE id='task-test'", (raw,))
        result = self.client.call("get_progress", {"task_id": "task-test", "read_token": created["read_token"]})["structuredContent"]["state"]
        self.assertFalse(result["finalized"])
        self.assertIsNone(result["finalized_at"])
        with sqlite3.connect(str(self.data / "progress.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT state FROM tasks WHERE id='task-test'").fetchone()[0], raw)
            for field, value in (("finalized", "false"), ("unknown", True)):
                bad = {**legacy, field: value}
                db.execute("UPDATE tasks SET state=? WHERE id='task-test'", (json.dumps(bad),));db.commit()
                self.assertTrue(self.client.call("get_progress", {"task_id": "task-test", "read_token": created["read_token"]})["isError"])

    def test_package_data_directory_is_refused_without_creation(self):
        data = SERVER.parent / "forbidden-runtime"
        result = subprocess.run([sys.executable, "-B", str(SERVER), "--data-dir", str(data)], input=b"", capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(data.exists())

    def test_symlink_data_and_database_are_refused(self):
        bad = Path(self.temp.name).resolve() / "link"
        bad.symlink_to(self.data, target_is_directory=True)
        result = subprocess.run([sys.executable, "-B", str(SERVER), "--data-dir", str(bad)], input=b"", capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.client.close()
        db = self.data / "progress.sqlite3"
        target = Path(self.temp.name).resolve() / "untouched"
        target.write_bytes(b"keep")
        db.unlink()
        db.symlink_to(target)
        result = subprocess.run([sys.executable, "-B", str(SERVER), "--data-dir", str(self.data)], input=b"", capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(target.read_bytes(), b"keep")


class ReconciliationTests(unittest.TestCase):
    """Real stdio calls and durable SQLite, with no owner capabilities in UI."""
    setUp = ProtocolTests.setUp
    tearDown = ProtocolTests.tearDown
    start = ProtocolTests.start
    fields = ProtocolTests.fields
    create = ProtocolTests.create
    read = ProtocolTests.read
    def writing(self, created, state=None):
        return {"task_id": created["state"]["task_id"], "write_token": created["write_token"],
            "expected_revision": (state or created["state"])["revision"]}

    def display_fields(self, state):
        return copy.deepcopy({key: state[key] for key in ("title", "actor", "current", "blocker", "stages")})

    def update(self, created, state=None, **kwargs):
        reply = self.client.call("update_progress", {**self.writing(created, state), **kwargs})
        self.assertNotIn("isError", reply, reply)
        return reply["structuredContent"]["state"]

    def test_reconciliation_add_while_running_and_after_partial_completion(self):
        created = self.create()
        state = self.update(created, patch={"stages": [{"id": "build", "status": "completed", "detail": "Build verified by protocol checks"}]})
        fields = self.display_fields(state)
        fields["stages"][1]["status"] = "running"
        fields["stages"].append({"id": "new-scope", "title": "New requirement", "status": "pending"})
        updated = self.update(created, state, **fields, plan_change={"summary": "User added an export check"})
        self.assertEqual(updated["stages"][0], state["stages"][0])
        self.assertEqual([s["status"] for s in updated["stages"]], ["completed", "running", "pending"])
        self.assertEqual(updated["plan"]["revision"], 1)
        self.assertEqual(updated["plan"]["retired_stages"], [])
        self.assertEqual(updated["task_id"], created["state"]["task_id"])
        self.assertNotIn("open_progress_panel", self.client.tool_calls)
        regressed = copy.deepcopy(fields)
        regressed["stages"][0]["status"] = "running"
        self.assertTrue(self.client.call("update_progress", {**self.writing(created, updated), **regressed})["isError"])
        self.assertEqual(self.read(created), updated)

    def test_reconciliation_remove_pending_and_completed_preserves_exact_history(self):
        created = self.create()
        done = self.update(created, patch={"stages": [{"id": "build", "status": "completed", "detail": "Confirmed implementation evidence"}]})
        fields = self.display_fields(done)
        fields["stages"] = [{"id": "replacement", "title": "Current requirement", "status": "pending"}]
        state = self.update(created, done, **fields)
        history = state["plan"]["retired_stages"]
        self.assertEqual([entry["stage"] for entry in history], done["stages"])
        self.assertEqual(history[0]["stage"]["status"], "completed")
        self.assertEqual(history[1]["stage"]["status"], "pending")
        self.assertTrue(all(e["retired_revision"] == 1 and e["retired_at"] == state["plan"]["changed_at"] for e in history))
        patched = self.update(created, state, patch={"current": "Continue authorized scope"})
        self.assertEqual(patched["plan"], state["plan"])
        for arguments in ({"patch": {"stages": [{"id": "build", "status": "completed"}]}},
                {**self.display_fields(patched), "stages": done["stages"]},
                {"patch": {}, "plan": state["plan"]}):
            self.assertTrue(self.client.call("update_progress", {**self.writing(created, patched), **arguments})["isError"])
        self.assertEqual(self.read(created), patched)

    def test_reconciliation_rename_reorder_and_semantic_refinement_keep_ids(self):
        created = self.create()
        renamed = self.update(created, patch={"stages": [{"id": "verify", "title": "Verify the revised export"}]})
        self.assertEqual(renamed["stages"][0], created["state"]["stages"][0])
        self.assertEqual(renamed["stages"][1]["id"], "verify")
        fields = self.display_fields(renamed)
        fields["stages"] = [fields["stages"][0], {"id": "later", "title": "Later work", "status": "pending"}, fields["stages"][1]]
        expanded = self.update(created, renamed, **fields)
        fields = self.display_fields(expanded)
        fields["stages"][1:] = reversed(fields["stages"][1:])
        ordered = self.update(created, expanded, **fields)
        self.assertEqual([s["id"] for s in ordered["stages"]], ["build", "verify", "later"])
        refined = self.update(created, ordered, patch={"stages": [{"id": "verify", "detail": "Includes an explicit export check"}]},
            plan_change={"summary": "Export verification refined"})
        self.assertEqual(refined["plan"]["revision"], 4)
        self.assertEqual(refined["stages"][0], ordered["stages"][0])

    def test_reconciliation_four_active_agents_require_confirmed_patch_before_retirement(self):
        created = self.create()
        active = [{"id": "assignment-" + str(i), "actor": "Worker " + str(i), "status": "running", "detail": "Assigned work"} for i in range(4)]
        state = self.update(created, patch={"stages": [{"id": "build", "agents": active}]})
        fields = self.display_fields(state)
        fields["stages"].append({"id": "extra", "title": "Added unrelated work", "status": "pending"})
        added = self.update(created, state, **fields, plan_change={"summary": "Additional requirement"})
        self.assertEqual(added["stages"][0]["agents"], active)
        removal = self.display_fields(added)
        removal["stages"] = removal["stages"][1:]
        denied = self.client.call("update_progress", {**self.writing(created, added), **removal})
        self.assertTrue(denied["isError"])
        self.assertIn("confirm", denied["content"][0]["text"])
        self.assertEqual(self.read(created), added)
        terminal = [{**a, "status": "completed" if i == 0 else "cancelled", "detail": "Verified result" if i == 0 else "Cancellation confirmed"} for i, a in enumerate(active)]
        settled = self.update(created, added, patch={"stages": [{"id": "build", "agents": terminal}]})
        removed = self.update(created, settled, **removal, plan_change={"summary": "Affected assignments reconciled"})
        self.assertEqual(removed["plan"]["retired_stages"][0]["stage"]["agents"], terminal)
        # Late reports cannot restore the retired stage, even with a fresh CAS.
        for arguments in ({"patch": {"stages": [{"id": "build", "agents": active}]}},
                self.display_fields(added),
                {**self.display_fields(removed), "stages": [{"id": "fresh", "title": "Fresh work", "status": "running", "agents": active}]}):
            self.assertTrue(self.client.call("update_progress", {**self.writing(created, removed), **arguments})["isError"])
        self.assertEqual(self.read(created), removed)

    def test_reconciliation_cas_reconstructs_latest_verified_progress_once(self):
        from concurrent.futures import ThreadPoolExecutor
        created = self.create()
        other = self.start()
        fields = self.display_fields(created["state"])
        fields["stages"].append({"id": "added", "title": "Authorized addition", "status": "pending"})
        with ThreadPoolExecutor(max_workers=2) as pool:
            structural = pool.submit(self.client.call, "update_progress", {**self.writing(created), **fields, "plan_change": {"summary": "Added check"}})
            progress = pool.submit(other.call, "update_progress", {**self.writing(created), "patch": {"stages": [{"id": "build", "status": "completed", "detail": "Latest verified result"}]}})
            first, second = structural.result(), progress.result()
        self.assertEqual(sum(bool(r.get("isError")) for r in (first, second)), 1)
        latest = self.read(created)
        if first.get("isError"):
            intent = self.display_fields(latest)
            intent["stages"].append(fields["stages"][-1])
            latest = self.update(created, latest, **intent, plan_change={"summary": "Added check"})
        else:
            latest = other.call("update_progress", {**self.writing(created, latest), "patch": {"stages": [{"id": "build", "status": "completed", "detail": "Latest verified result"}]}})["structuredContent"]["state"]
        self.assertEqual(latest["revision"], 3)
        self.assertEqual(latest["stages"][0]["status"], "completed")
        self.assertEqual(latest["stages"][0]["detail"], "Latest verified result")
        self.assertEqual(latest["stages"][-1]["id"], "added")
        self.assertEqual(self.client.tool_calls.count("get_progress"), 1)
        stale = self.client.call("update_progress", {**self.writing(created, latest), **fields})
        self.assertTrue(stale["isError"])
        self.assertEqual(self.read(created), latest)

    def test_reconciliation_retained_compaction_and_finalization_preserve_history(self):
        created = self.create()
        self.client.call("open_progress_panel", {"task_id": "task-test", "read_token": created["read_token"]})
        first = self.update(created, patch={"stages": [{"id": "verify", "title": "Changed scope"}]}, plan_change={"summary": "Scope refined"})
        self.client.close()
        self.client = self.start()
        retained = self.read(created)
        self.assertEqual(retained, first)
        fields = self.display_fields(retained)
        fields["stages"] = fields["stages"][:1]
        reconciled = self.update(created, retained, **fields)
        finalized = self.client.call("finish_progress", {**self.writing(created, reconciled), **self.display_fields(reconciled)})["structuredContent"]["state"]
        self.assertEqual(finalized["plan"], reconciled["plan"])
        self.assertTrue(self.client.call("update_progress", {**self.writing(created, finalized), "patch": {}, "plan_change": {"summary": "Must reject"}})["isError"])
        self.assertEqual(self.read(created), finalized)
        self.assertEqual(self.client.tool_calls.count("create_progress"), 0)
        self.assertEqual(self.client.tool_calls.count("open_progress_panel"), 0)

    def test_reconciliation_malformed_changes_and_history_bounds_are_atomic(self):
        created = self.create()
        malformed = [None, [], {}, {"summary": ""}, {"summary": " "}, {"summary": "x" * 601},
            {"summary": "\ud800"}, {"summary": "valid", "retired_stages": []}, {"summary": 1}]
        for change in malformed:
            self.assertTrue(self.client.call("update_progress", {**self.writing(created), "patch": {}, "plan_change": change})["isError"])
            self.assertEqual(self.read(created), created["state"])
        state = created["state"]
        for i in range(31):
            fields = self.display_fields(state)
            fields["stages"] = [{"id": "fresh-" + str(i), "title": "Fresh pending work", "status": "pending"}]
            state = self.update(created, state, **fields)
        self.assertEqual(len(state["plan"]["retired_stages"]), 32)
        fields = self.display_fields(state)
        fields["stages"] = [{"id": "overflow", "title": "Cannot prune history", "status": "pending"}]
        rejected = self.client.call("update_progress", {**self.writing(created, state), **fields})
        self.assertTrue(rejected["isError"])
        self.assertIn("32 retired", rejected["content"][0]["text"])
        self.assertEqual(self.read(created), state)

    def test_reconciliation_complete_snapshot_bound_includes_retirement_evidence(self):
        fields = {"title": "Large evidence", "stages": [{"id": "old-" + str(i), "title": "x" * 240,
            "status": "completed", "actor": "x" * 160, "detail": "x" * 600} for i in range(32)]}
        created = self.client.call("create_progress", {"task_id": "large", **fields})["structuredContent"]
        fields["stages"] = [{**s, "id": "new-" + str(i), "status": "pending"} for i, s in enumerate(fields["stages"])]
        # Retirement doubles stored evidence; the request alone is below 64 KiB.
        self.assertLess(len(json.dumps(fields).encode()), 65536)
        rejected = self.client.call("update_progress", {**self.writing(created), **fields})
        self.assertTrue(rejected["isError"])
        self.assertIn("64 KiB", rejected["content"][0]["text"])
        self.assertEqual(self.read(created, "large"), created["state"])

    def test_reconciliation_legacy_snapshot_has_no_metadata_until_plan_changes(self):
        created = self.create()
        self.assertNotIn("plan", self.read(created))
        normal = self.update(created, patch={"current": "Normal progress"})
        self.assertNotIn("plan", normal)
        changed = self.update(created, normal, patch={"stages": [{"id": "verify", "title": "Revised requirement"}]})
        self.assertEqual(changed["plan"]["revision"], 1)
        self.assertEqual(changed["plan"]["retired_stages"], [])


class CleanupTests(unittest.TestCase):
    """Retention tests use only a fresh private SQLite directory per test."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cleanup-")
        self.data = Path(self.temp.name).resolve() / "private-data"
        self.clients = []
        self.client = self.start()
        self.store = progress_server.Store(self.data, auto_cleanup_finalized=True)

    def tearDown(self):
        self.store.close()
        for client in self.clients:
            client.close()
        self.temp.cleanup()

    def start(self, enabled=False):
        client = Client(self.data, ("--auto-cleanup-finalized",) if enabled else ())
        self.clients.append(client)
        client.initialize()
        return client

    def fields(self):
        return {"title": "Retention", "stages": [{"id": "work", "title": "Work", "status": "running"}]}

    def fill(self, finalized=()):
        created = {}
        for index in range(128):
            ident = "retained-%03d" % index
            created[ident] = self.store.create({"task_id": ident, **self.fields()})
            if index in finalized:
                self.store.finish({"task_id": ident, "write_token": created[ident]["write_token"],
                    "expected_revision": 1, **self.fields()})
        return created

    def rows(self):
        return self.store.db.execute("SELECT * FROM tasks ORDER BY id").fetchall()

    def timestamp(self, ident, value):
        state = json.loads(self.store.db.execute("SELECT state FROM tasks WHERE id=?", (ident,)).fetchone()[0])
        state.update(updated_at=value, finalized_at=value)
        self.store.db.execute("UPDATE tasks SET state=? WHERE id=?", (json.dumps(state), ident))

    def create(self, client, ident="new-task"):
        return client.call("create_progress", {"task_id": ident, **self.fields()})

    def compete(self, operations):
        import concurrent.futures
        import threading
        barrier = threading.Barrier(2)
        def run(operation):
            barrier.wait(timeout=3)
            return operation()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=6) for future in futures]

    def test_default_off_retains_full_history_and_existing_capabilities(self):
        created = self.fill((0,))
        before = self.rows()
        denied = self.create(self.client)
        self.assertTrue(denied["isError"])
        self.assertIn("128 retained executions", denied["content"][0]["text"])
        self.assertEqual(self.rows(), before)
        self.client.close()
        default_restart = self.start()
        self.assertEqual(self.rows(), before)
        retained = created["retained-000"]
        self.assertTrue(default_restart.call("get_progress", {"task_id": "retained-000",
            "read_token": retained["read_token"]})["structuredContent"]["state"]["finalized"])
        self.assertEqual(self.rows(), before)
        for value in (None, 0, 1, "true", []):
            with self.subTest(value=value), self.assertRaises(progress_server.Invalid):
                progress_server.Store(self.data, auto_cleanup_finalized=value)

    def test_retention_metadata_is_per_server_and_keeps_tool_shapes(self):
        default_tools = self.client.request("tools/list")["result"]["tools"]
        enabled_tools = self.start(True).request("tools/list")["result"]["tools"]
        for default, enabled in zip(default_tools, enabled_tools):
            expected = copy.deepcopy(default)
            if default["name"] == "create_progress":
                expected["annotations"]["destructiveHint"] = True
            self.assertEqual(enabled, expected)
        self.assertEqual(self.client.request("tools/list")["result"]["tools"], default_tools)
        enabled_server = progress_server.Server(self.store); enabled_server.ready = True
        disabled_store = progress_server.Store(self.data)
        try:
            disabled_server = progress_server.Server(disabled_store); disabled_server.ready = True
            self.assertEqual(enabled_server.call("tools/list", {}), {"tools": enabled_tools})
            self.assertEqual(disabled_server.call("tools/list", {}), {"tools": default_tools})
            self.assertFalse(progress_server.TOOLS[0]["annotations"]["destructiveHint"])
        finally:
            disabled_store.close()

    def test_opt_in_below_capacity_and_non_create_calls_never_delete(self):
        created = self.store.create({"task_id": "retained", **self.fields()})
        final = self.store.finish({"task_id": "retained", "write_token": created["write_token"],
            "expected_revision": 1, **self.fields()})["state"]
        before = self.rows()[0]
        client = self.start(True)
        self.assertEqual(self.rows(), [before])
        self.assertNotIn("isError", self.create(client))
        self.assertEqual(self.rows()[1], before)
        self.assertEqual(client.call("get_progress", {"task_id": "retained", "read_token": created["read_token"]})["structuredContent"]["state"], final)
        self.assertTrue(client.call("finish_progress", {"task_id": "retained", "write_token": created["write_token"],
            "expected_revision": 2, **self.fields()})["isError"])
        self.assertEqual(self.rows()[1], before)

    def test_oldest_uses_utc_finalization_then_id_and_preserves_survivor_bytes(self):
        self.fill((0, 1, 2))
        # retained-001 and 002 are equally old in UTC; the id resolves that tie.
        self.timestamp("retained-000", "2020-01-01T00:00:00+00:00")
        self.timestamp("retained-001", "2020-01-01T00:30:00+02:00")
        self.timestamp("retained-002", "2019-12-31T22:30:00Z")
        before = self.rows()
        client = self.start(True)
        self.assertNotIn("isError", self.create(client))
        after = self.rows()
        self.assertEqual(len(after), 128)
        self.assertEqual([row for row in after if row[0] != "new-task"],
            [row for row in before if row[0] != "retained-001"])
        self.assertNotIn("isError", self.create(client, "next-task"))
        self.assertFalse(any(row[0] == "retained-002" for row in self.rows()))

    def test_stale_completed_and_legacy_unfinished_rows_are_never_eligible(self):
        created = self.fill()
        for index in range(128):
            ident = "retained-%03d" % index
            state = copy.deepcopy(created[ident]["state"])
            state["updated_at"] = "2000-01-01T00:00:00+00:00"
            state["stages"][0]["status"] = "completed"
            if index % 2:
                state.pop("finalized"); state.pop("finalized_at")
            self.store.db.execute("UPDATE tasks SET state=? WHERE id=?", (json.dumps(state), ident))
        before = self.rows()
        self.assertTrue(self.create(self.start(True))["isError"])
        self.assertEqual(self.rows(), before)

    def test_duplicate_oldest_identity_and_invalid_input_leave_all_bytes(self):
        self.fill((0,))
        client = self.start(True)
        before = self.rows()
        duplicate = self.create(client, "retained-000")
        self.assertTrue(duplicate["isError"])
        self.assertIn("choose a new id", duplicate["content"][0]["text"])
        invalid = client.call("create_progress", {"task_id": "invalid-input", **self.fields(), "title": ""})
        self.assertTrue(invalid["isError"])
        oversized = {"title": "Large", "stages": [{"id": "s" + str(i), "title": "😀" * 240,
            "status": "running", "detail": "😀" * 600} for i in range(32)]}
        with self.assertRaisesRegex(progress_server.Invalid, "Snapshot exceeds"):
            self.store.create({"task_id": "too-large", **oversized})
        self.assertEqual(self.rows(), before)

    def test_corrupt_retained_states_fail_closed_without_any_deletion(self):
        self.fill((0,))
        client = self.start(True)
        original = self.rows()[0][-1]
        state = json.loads(original)
        malformed = ["{", json.dumps({**state, "finalized": "true"}),
            json.dumps({**state, "finalized_at": None}),
            json.dumps({**state, "finalized_at": "bad", "updated_at": "bad"}),
            json.dumps({**state, "finalized_at": "2020-01-01T00:00:00", "updated_at": "2020-01-01T00:00:00"}),
            json.dumps({**state, "task_id": "other"}), json.dumps({**state, "revision": 99}),
            json.dumps({**state, "stages": []}), original[:-1] + ',"finalized":true}']
        for encoded in malformed:
            with self.subTest(encoded=encoded):
                self.store.db.execute("UPDATE tasks SET state=? WHERE id='retained-000'", (encoded,))
                before = self.rows()
                reply = client.request("tools/call", {"name": "create_progress", "arguments": {"task_id": "new-task", **self.fields()}})
                self.assertTrue(reply.get("error") or reply["result"].get("isError"))
                self.assertEqual(self.rows(), before)
        self.store.db.execute("UPDATE tasks SET state=? WHERE id='retained-000'", (original,))
        # Corruption in an unfinished row is not ignored while choosing a victim.
        self.store.db.execute("UPDATE tasks SET state='{}' WHERE id='retained-127'")
        before = self.rows()
        self.assertTrue(self.create(client)["isError"])
        self.assertEqual(self.rows(), before)

    def test_insert_failure_rolls_back_victim_and_retry_succeeds(self):
        self.fill((0,))
        before = self.rows()
        self.store.db.execute("CREATE TRIGGER reject_new BEFORE INSERT ON tasks BEGIN SELECT RAISE(ABORT, 'test insertion failure'); END")
        self.assertTrue(self.create(self.start(True))["isError"])
        self.assertEqual(self.rows(), before)
        self.store.db.execute("DROP TRIGGER reject_new")
        self.assertNotIn("isError", self.create(self.clients[-1]))
        self.assertEqual(len(self.rows()), 128)

    def test_over_limit_database_is_not_pruned(self):
        self.fill((0,))
        row = list(self.rows()[0]); row[0] = "extra"
        state = json.loads(row[-1]); state["task_id"] = "extra"; row[-1] = json.dumps(state)
        self.store.db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", row)
        before = self.rows()
        self.assertTrue(self.create(self.start(True))["isError"])
        self.assertEqual(self.rows(), before)

    def test_real_sqlite_held_lock_failure_preserves_rows_then_retry(self):
        self.fill((0,))
        client = self.start(True)
        before = self.rows()
        self.store.db.execute("BEGIN IMMEDIATE")
        try:
            # SQLite waits 2 seconds for the lock; allow CI scheduling overhead.
            reply = client.request("tools/call", {"name": "create_progress", "arguments": {"task_id": "new-task", **self.fields()}}, timeout=8)
            self.assertEqual(reply["error"]["code"], -32603)
            self.assertEqual(self.rows(), before)
        finally:
            self.store.db.execute("ROLLBACK")
        self.assertNotIn("isError", self.create(client))
        self.assertEqual(len(self.rows()), 128)

    def test_two_real_servers_compete_for_one_eligible_row(self):
        self.fill((0,))
        first, second = self.start(True), self.start(True)
        replies = self.compete([lambda: self.create(first, "new-a"), lambda: self.create(second, "new-b")])
        self.assertEqual(sum(not reply.get("isError", False) for reply in replies), 1)
        self.assertEqual(len(self.rows()), 128)
        self.assertFalse(any(row[0] == "retained-000" for row in self.rows()))

    def test_two_real_servers_with_two_eligible_rows_both_succeed(self):
        self.fill((0, 1))
        first, second = self.start(True), self.start(True)
        before = self.rows()
        replies = self.compete([lambda: self.create(first, "new-a"), lambda: self.create(second, "new-b")])
        self.assertTrue(all(not reply.get("isError", False) for reply in replies))
        self.assertEqual(len(self.rows()), 128)
        self.assertEqual([row for row in self.rows() if row[0].startswith("retained-")], before[2:])

    def test_cleanup_and_update_serialize_without_changing_survivor_authority(self):
        created = self.fill((0,))
        first, second = self.start(True), self.start(True)
        args = {"task_id": "retained-001", "write_token": created["retained-001"]["write_token"],
            "expected_revision": 1, "patch": {"current": "Updated survivor"}}
        replies = self.compete([lambda: self.create(first), lambda: second.call("update_progress", args)])
        self.assertTrue(all(not reply.get("isError", False) for reply in replies))
        survivor = next(row for row in self.rows() if row[0] == "retained-001")
        self.assertEqual(survivor[1:3], (progress_server.digest(args["write_token"]), created["retained-001"]["read_token"]))
        self.assertEqual(survivor[3], 2)
        self.assertEqual(json.loads(survivor[4])["current"], "Updated survivor")

    def test_cleanup_and_finish_serialize_with_no_unconfirmed_victim(self):
        created = self.fill()
        first, second = self.start(True), self.start(True)
        args = {"task_id": "retained-000", "write_token": created["retained-000"]["write_token"],
            "expected_revision": 1, **self.fields()}
        replies = self.compete([lambda: self.create(first), lambda: second.call("finish_progress", args)])
        self.assertNotIn("isError", replies[1])
        self.assertTrue(replies[1]["structuredContent"]["state"]["finalized"])
        self.assertEqual(len(self.rows()), 128)
        if replies[0].get("isError"):
            self.assertTrue(json.loads(self.rows()[0][-1])["finalized"])
            self.assertNotIn("isError", self.create(first))
        else:
            self.assertFalse(any(row[0] == "retained-000" for row in self.rows()))

    def test_restart_deleted_capabilities_and_reused_id_reject_old_tokens(self):
        created = self.fill((0,))
        before = self.rows()
        client = self.start(True)
        self.assertNotIn("isError", self.create(client))
        client.close()
        client = self.start()
        victim = created["retained-000"]
        opening = {"task_id": "retained-000", "read_token": victim["read_token"]}
        writing = {"task_id": "retained-000", "write_token": victim["write_token"], "expected_revision": 2, **self.fields()}
        for name, args in (("get_progress", opening), ("open_progress_panel", opening), ("update_progress", writing), ("finish_progress", writing)):
            self.assertTrue(client.call(name, args)["isError"])
        self.assertEqual([row for row in self.rows() if row[0] != "new-task"], before[1:])
        # Free another confirmed row and explicitly reuse the deleted id.
        self.store.finish({"task_id": "retained-001", "write_token": created["retained-001"]["write_token"],
            "expected_revision": 1, **self.fields()})
        replacement = self.create(self.start(True), "retained-000")["structuredContent"]
        self.assertNotEqual(replacement["read_token"], victim["read_token"])
        self.assertNotEqual(replacement["write_token"], victim["write_token"])
        self.assertTrue(client.call("get_progress", opening)["isError"])
        self.assertTrue(client.call("update_progress", {**writing, "expected_revision": 1})["isError"])
        self.assertEqual(client.call("get_progress", {"task_id": "retained-000", "read_token": replacement["read_token"]})["structuredContent"]["state"], replacement["state"])


if __name__ == "__main__":
    unittest.main()
