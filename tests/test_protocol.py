"""Bounded real stdio, SQLite restart and authorization tests. No sockets."""
import json
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


def assert_schema(value, spec):
    """Validate the declared JSON Schema subset against actual protocol output."""
    if "oneOf" in spec:
        matches = 0
        for choice in spec["oneOf"]:
            try:
                assert_schema(value, choice)
                matches += 1
            except AssertionError:
                pass
        assert matches == 1, "Output must match exactly one schema alternative"
        return
    kind = spec["type"]
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

    def receive(self):
        if not self.selector.select(4):
            raise AssertionError("Stdio server did not respond within 4 seconds")
        return json.loads(self.process.stdout.readline())

    def request(self, method, params=None):
        ident = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        reply = self.receive()
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


if __name__ == "__main__":
    unittest.main()
