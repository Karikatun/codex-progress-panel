#!/usr/bin/env python3
"""Local, dependency-free MCP progress panel. No sockets or background workers."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import sys
from datetime import datetime, timezone

VERSION = "0.1.0"
URI = "ui://progress/panel.html"
MIME = "text/html;profile=mcp-app"
MAX_LINE = 65536
MAX_TASKS = 128
STATUSES = ("pending", "running", "blocked", "completed")
ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
TOKEN = re.compile(r"[a-f0-9]{64}\Z")
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")


class Invalid(ValueError):
    pass


def exact_object(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise Invalid("Invalid fields")
    return value



def protocol_params(value, required=(), optional=()):
    """Validate the protocol envelope without changing any tool argument schema."""
    exact_object(value, required, (*optional, "_meta"))
    if "_meta" in value:
        meta = value["_meta"]
        if not isinstance(meta, dict):
            raise Invalid("Invalid protocol metadata")
        if "progressToken" in meta and not isinstance(meta["progressToken"], str) and type(meta["progressToken"]) not in (int, float):
            raise Invalid("Invalid progress token")
    # Metadata is untrusted context, never authorization or task data.
    return value


def single_page_params(value):
    protocol_params(value, optional=("cursor",))
    # These static catalogs fit in one page and never issue a nextCursor.
    # Any supplied cursor, including an empty token, is therefore unissued.
    if "cursor" in value:
        raise Invalid("Invalid cursor")


def text_field(value, limit, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise Invalid("Invalid text")
    if any((ord(c) < 32 and c not in "\n\t") or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise Invalid("Invalid text")
    return value


def safe_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise Invalid("Invalid task or stage id")
    return value


def token(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise Invalid("Task unavailable or invalid capability")
    return value


def revision(value):
    if type(value) is not int or not 1 <= value < 2**53:
        raise Invalid("Invalid revision")
    return value


def snapshot_fields(value):
    exact_object(value, ("title", "stages"), ("actor", "current", "blocker"))
    result = {"title": text_field(value["title"], 240)}
    for field in ("actor", "current", "blocker"):
        result[field] = text_field(value.get(field, ""), 600, empty=True)
    stages = value["stages"]
    if not isinstance(stages, list) or not 1 <= len(stages) <= 32:
        raise Invalid("Supply 1 to 32 stages")
    seen = set()
    result["stages"] = []
    for stage in stages:
        exact_object(stage, ("id", "title", "status"), ("actor", "detail"))
        ident = safe_id(stage["id"])
        if ident in seen or stage["status"] not in STATUSES:
            raise Invalid("Invalid stage identity or status")
        seen.add(ident)
        result["stages"].append({"id": ident, "title": text_field(stage["title"], 240),
            "status": stage["status"], "actor": text_field(stage.get("actor", ""), 160, empty=True),
            "detail": text_field(stage.get("detail", ""), 600, empty=True)})
    if any(s["status"] == "blocked" for s in result["stages"]) and not result["blocker"].strip():
        raise Invalid("Blocked stages require a blocker")
    return result


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def private_directory(path):
    """Reject symlinks in the configured path; create only its final component."""
    path = Path(path)
    package_root = Path(__file__).resolve().parent
    resolved = path.resolve()
    source_root = package_root.parent.parent
    protected_roots = [package_root]
    if (source_root / ".agents/plugins/marketplace.json").is_file():
        protected_roots.append(source_root)
    if any(resolved == root or root in resolved.parents for root in protected_roots):
        raise Invalid("Data directory must be outside the plugin package")
    if not path.is_absolute():
        raise Invalid("Data directory must be absolute")
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            if part.is_symlink() or not part.is_dir():
                raise Invalid("Unsafe data directory")
    if not path.exists():
        path.mkdir(mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise Invalid("Data directory must be private and owned by this user")
    return path


class Store:
    def __init__(self, data_dir):
        data_dir = private_directory(data_dir)
        db_path = data_dir / "progress.sqlite3"
        # Refuse SQLite sidecars that could redirect reads/writes outside this directory.
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = Path(str(db_path) + suffix)
            if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
                raise Invalid("Unsafe state file")
            if candidate.exists():
                info = candidate.stat()
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077 or info.st_nlink != 1:
                    raise Invalid("State file must be private and owned by this user")
        self.db = sqlite3.connect(str(db_path), timeout=2, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, write_hash TEXT NOT NULL, read_token TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL)")

    def close(self):
        self.db.close()

    def authenticated(self, task_id, capability, write=False):
        safe_id(task_id)
        token(capability)
        row = self.db.execute("SELECT write_hash, read_token, revision, state FROM tasks WHERE id=?", (task_id,)).fetchone()
        expected = row[0 if write else 1] if row else "0" * 64
        actual = digest(capability) if write else capability
        if not row or not hmac.compare_digest(expected, actual):
            raise Invalid("Task unavailable or invalid capability")
        state = json.loads(row[3])
        exact_object(state, ("task_id", "revision", "updated_at", "title", "stages", "actor", "current", "blocker"), ("finalized", "finalized_at"))
        # Legacy snapshots remain readable without mutating their stored bytes.
        state.setdefault("finalized", False)
        state.setdefault("finalized_at", None)
        if type(state["finalized"]) is not bool or (state["finalized"] != (state["finalized_at"] is not None)):
            raise Invalid("Stored finalization is invalid")
        if state["finalized"]:
            text_field(state["finalized_at"], 40)
            if state["finalized_at"] != state["updated_at"]:
                raise Invalid("Stored finalization is invalid")
        snapshot_fields({k: state[k] for k in ("title", "stages", "actor", "current", "blocker")})
        if state["task_id"] != task_id or state["revision"] != row[2]:
            raise Invalid("Stored state is invalid")
        revision(state["revision"])
        text_field(state["updated_at"], 40)
        return state, row[1]

    def create(self, args):
        exact_object(args, ("task_id", "title", "stages"), ("actor", "current", "blocker"))
        task_id = safe_id(args["task_id"])
        state = snapshot_fields({k: v for k, v in args.items() if k != "task_id"})
        state.update(task_id=task_id, revision=1, updated_at=datetime.now(timezone.utc).isoformat(), finalized=False, finalized_at=None)
        write_token, read_token = secrets.token_hex(32), secrets.token_hex(32)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT count(*) FROM tasks").fetchone()[0] >= MAX_TASKS:
                raise Invalid("Task capacity reached")
            self.db.execute("INSERT INTO tasks VALUES (?,?,?,?,?)", (task_id, digest(write_token), read_token, 1, json.dumps(state, ensure_ascii=False)))
            self.db.execute("COMMIT")
        except sqlite3.IntegrityError:
            self.db.execute("ROLLBACK")
            raise Invalid("Task unavailable; choose a new id or use its existing capability")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return {"state": state, "write_token": write_token, "read_token": read_token}

    def update(self, args):
        return self.replace(args, finalize=False)

    def finish(self, args):
        return self.replace(args, finalize=True)

    def replace(self, args, finalize):
        exact_object(args, ("task_id", "write_token", "expected_revision", "title", "stages"), ("actor", "current", "blocker"))
        expected = revision(args["expected_revision"])
        state = snapshot_fields({k: v for k, v in args.items() if k not in ("task_id", "write_token", "expected_revision")})
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old, _ = self.authenticated(args["task_id"], args["write_token"], write=True)
            if old["finalized"]:
                raise Invalid("Task finalized; create a new execution")
            if old["revision"] != expected:
                raise Invalid("Stale revision; reopen the authenticated task before updating")
            timestamp = datetime.now(timezone.utc).isoformat()
            state.update(task_id=args["task_id"], revision=expected + 1, updated_at=timestamp,
                finalized=finalize, finalized_at=timestamp if finalize else None)
            revision(state["revision"])
            self.db.execute("UPDATE tasks SET revision=?, state=? WHERE id=?", (state["revision"], json.dumps(state, ensure_ascii=False), args["task_id"]))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return {"state": state}


def schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


ID_SCHEMA = {"type": "string", "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$", "maxLength": 64}
TOKEN_SCHEMA = {"type": "string", "pattern": "^[a-f0-9]{64}$", "maxLength": 64}
TEXT_SCHEMA = {"type": "string", "maxLength": 600}
FIELDS = {"title": {"type": "string", "minLength": 1, "maxLength": 240}, "actor": TEXT_SCHEMA,
    "current": TEXT_SCHEMA, "blocker": TEXT_SCHEMA,
    "stages": {"type": "array", "minItems": 1, "maxItems": 32, "items": schema({"id": ID_SCHEMA,
        "title": {"type": "string", "minLength": 1, "maxLength": 240},
        "status": {"type": "string", "enum": list(STATUSES)},
        "actor": {"type": "string", "maxLength": 160}, "detail": TEXT_SCHEMA}, ("id", "title", "status"))}}


STAGE_OUTPUT = {**FIELDS["stages"]["items"], "required": ["id", "title", "status", "actor", "detail"]}
STATE_OUTPUT = schema({**FIELDS, "stages": {**FIELDS["stages"], "items": STAGE_OUTPUT},
    "task_id": ID_SCHEMA, "revision": {"type": "integer", "minimum": 1, "maximum": 2**53-1},
    "updated_at": {"type": "string", "minLength": 1, "maxLength": 40, "format": "date-time"},
    "finalized": {"type": "boolean"},
    "finalized_at": {"oneOf": [{"type": "string", "minLength": 1, "maxLength": 40, "format": "date-time"}, {"type": "null"}]}},
    ("task_id", "revision", "updated_at", "title", "stages", "actor", "current", "blocker", "finalized", "finalized_at"))
STATE_RESULT = schema({"state": STATE_OUTPUT}, ("state",))
CREATE_RESULT = schema({"state": STATE_OUTPUT, "write_token": TOKEN_SCHEMA, "read_token": TOKEN_SCHEMA},
    ("state", "write_token", "read_token"))
OPEN_RESULT = schema({"state": {"oneOf": [STATE_OUTPUT, {"type": "null"}]}}, ("state",))


def tool(name, description, input_schema, output_schema, read_only, meta):
    return {"name": name, "description": description, "inputSchema": input_schema, "outputSchema": output_schema,
        "annotations": {"readOnlyHint": read_only, "destructiveHint": False, "openWorldHint": False}, "_meta": meta}


TOOLS = [
    tool("create_progress", "Create explicit local task progress. Returns separate write and read capabilities; retain the write capability only for updates. Never include secrets or raw logs.",
        schema({"task_id": ID_SCHEMA, **FIELDS}, ("task_id", "title", "stages")), CREATE_RESULT, False, {"ui": {"visibility": ["model"]}}),
    tool("open_progress_panel", "Open one authenticated task's read-only progress panel. Empty arguments show an unbound empty panel. Requires create_progress first to bind a task.",
        schema({"task_id": ID_SCHEMA, "read_token": TOKEN_SCHEMA}), OPEN_RESULT, True,
        {"ui": {"resourceUri": URI, "visibility": ["model"]}}),
    tool("update_progress", "Replace an authenticated task progress snapshot with compare-and-swap revision. Completed means the named stage is done, not release or deployment proof.",
        schema({"task_id": ID_SCHEMA, "write_token": TOKEN_SCHEMA,
            "expected_revision": {"type": "integer", "minimum": 1, "maximum": 2**53-2}, **FIELDS},
            ("task_id", "write_token", "expected_revision", "title", "stages")), STATE_RESULT, False, {"ui": {"visibility": ["model"]}}),
    tool("finish_progress", "Freeze the final snapshot of this assistant execution. Irrevocable; blocked or pending stages may remain. Requires the write capability and current revision.",
        schema({"task_id": ID_SCHEMA, "write_token": TOKEN_SCHEMA,
            "expected_revision": {"type": "integer", "minimum": 1, "maximum": 2**53-2}, **FIELDS},
            ("task_id", "write_token", "expected_revision", "title", "stages")), STATE_RESULT, False, {"ui": {"visibility": ["model"]}}),
    tool("get_progress", "Read exactly one panel task using its read capability; no listing or writes.",
        schema({"task_id": ID_SCHEMA, "read_token": TOKEN_SCHEMA}, ("task_id", "read_token")), STATE_RESULT, True, {"ui": {"visibility": ["app"]}}),
]


class Server:
    def __init__(self, store):
        self.store, self.initialized, self.ready = store, False, False

    def call(self, method, params):
        if method == "initialize":
            protocol_params(params, ("protocolVersion", "capabilities", "clientInfo"))
            if self.initialized or not isinstance(params["capabilities"], dict) or not isinstance(params["clientInfo"], dict):
                raise Invalid("Invalid initialization")
            self.initialized = True
            version = params["protocolVersion"]
            return {"protocolVersion": version if version in PROTOCOLS else PROTOCOLS[0],
                "serverInfo": {"name": "codex-progress-panel", "version": VERSION}, "capabilities": {"tools": {}, "resources": {}}}
        if method == "ping":
            protocol_params(params)
            return {}
        if not self.ready:
            raise Invalid("Initialization required")
        if method == "tools/list":
            single_page_params(params)
            return {"tools": TOOLS}
        if method == "resources/list":
            single_page_params(params)
            return {"resources": [{"uri": URI, "name": "progress_panel", "title": "Этапы задачи", "mimeType": MIME}]}
        if method == "resources/templates/list":
            single_page_params(params)
            return {"resourceTemplates": []}
        if method == "resources/read":
            protocol_params(params, ("uri",))
            if params["uri"] != URI:
                raise Invalid("Unknown resource")
            return {"contents": [{"uri": URI, "mimeType": MIME,
                "text": Path(__file__).with_name("panel.html").read_text(encoding="utf-8"),
                "_meta": {"ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": [], "frameDomains": [], "baseUriDomains": []}}}}]}
        if method == "tools/call":
            protocol_params(params, ("name",), ("arguments",))
            name, args = params["name"], params.get("arguments", {})
            if name not in {t["name"] for t in TOOLS}:
                raise Invalid("Unknown tool")
            try:
                meta = {}
                if name == "create_progress":
                    data = self.store.create(args)
                elif name == "update_progress":
                    data = self.store.update(args)
                elif name == "finish_progress":
                    data = self.store.finish(args)
                elif name == "open_progress_panel":
                    exact_object(args, (), ("task_id", "read_token"))
                    if not args:
                        data = {"state": None}
                    elif set(args) != {"task_id", "read_token"}:
                        raise Invalid("Supply both task id and read capability")
                    else:
                        state, read_token = self.store.authenticated(args["task_id"], args["read_token"])
                        data, meta = {"state": state}, {"read_token": read_token}
                else:
                    exact_object(args, ("task_id", "read_token"))
                    state, _ = self.store.authenticated(args["task_id"], args["read_token"])
                    data = {"state": state}
                state = data.get("state")
                summary = "Panel has no bound task." if state is None else "Task {} · revision {} · {} stages".format(state["task_id"], state["revision"], len(state["stages"]))
                return {"content": [{"type": "text", "text": summary}], "structuredContent": data, "_meta": meta}
            except Invalid as exc:
                return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
        raise LookupError("Unknown method")

    def dispatch(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return error(None, -32600, "Invalid request")
        ident = message.get("id")
        if "id" not in message:
            if message["method"] == "notifications/initialized" and self.initialized:
                try:
                    protocol_params(message.get("params", {}))
                except Invalid:
                    return None  # Invalid notifications cannot advance the lifecycle.
                self.ready = True
            return None  # Requests disguised as notifications cannot change state.
        if not ((type(ident) is int and abs(ident) < 2**53) or (isinstance(ident, str) and len(ident) <= 128)):
            return error(None, -32600, "Invalid request id")
        try:
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise Invalid("Invalid params")
            result = self.call(message["method"], params)
            return {"jsonrpc": "2.0", "id": ident, "result": result}
        except Invalid as exc:
            return error(ident, -32602, str(exc))
        except LookupError:
            return error(ident, -32601, "Method not found")
        except Exception:
            return error(ident, -32603, "Local state operation failed")


def error(ident, code, message):
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Invalid("Duplicate JSON field")
        value[key] = item
    return value


def invalid_constant(_):
    raise Invalid("Invalid JSON constant")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(Path.home() / ".codex-progress-panel"), help="Absolute private directory. Its parent must exist; symlinks are rejected.")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        store = Store(args.data_dir)
    except Exception:
        print("progress-panel: private data directory is unavailable or unsafe", file=sys.stderr)
        return 1
    server = Server(store)
    try:
        while True:
            raw = sys.stdin.buffer.readline(MAX_LINE + 1)
            if not raw:
                break
            if len(raw) > MAX_LINE:
                print(json.dumps(error(None, -32700, "Message exceeds 64 KiB")), flush=True)
                break  # Do not buffer or drain an unbounded hostile line.
            try:
                message = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
                reply = server.dispatch(message)
            except (ValueError, UnicodeError, RecursionError):
                reply = error(None, -32700, "Invalid JSON")
            if reply is not None:
                print(json.dumps(reply, ensure_ascii=False, separators=(",", ":")), flush=True)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
