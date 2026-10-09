"""Portable distribution and copied-package stdio launch checks."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins/progress-panel"


class PackagingTests(unittest.TestCase):
    def test_release_identity_and_distribution_hygiene(self):
        plugin = json.loads((PACKAGE / "plugin.json").read_text())
        self.assertEqual(plugin["name"], "codex-progress-panel")
        self.assertEqual(plugin["version"], "0.1.0")
        self.assertEqual(plugin["license"], "MIT")
        self.assertFalse((PACKAGE / ".mcp.json").exists())
        self.assertFalse((PACKAGE / ".codex-plugin").exists())
        self.assertEqual((PACKAGE / "LICENSE").read_bytes(), (ROOT / "LICENSE").read_bytes())
        self.assertTrue((PACKAGE / "skills/progress-panel/SKILL.md").is_file())
        for entry in ROOT.rglob("*"):
            if ".git" in entry.parts:
                continue
            self.assertFalse(entry.is_symlink(), str(entry))
            if not entry.is_file():
                continue
            self.assertNotIn(entry.suffix, (".sqlite3", ".db", ".pyc", ".log"), str(entry))
            self.assertNotIn("__pycache__", entry.parts)
            self.assertFalse(entry.name.startswith(".env"))
            data = entry.read_bytes()
            self.assertNotIn(b"/" + b"Users/", data, str(entry))
            self.assertNotIn(b"/" + b"Library/Developer/", data, str(entry))
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(marketplace["plugins"][0]["name"], plugin["name"])
        self.assertEqual((ROOT / marketplace["plugins"][0]["source"]["path"]).resolve(), PACKAGE)

    def test_manifest_launches_copied_package_with_spaces_and_external_state(self):
        with tempfile.TemporaryDirectory(prefix="package-launch-") as temp:
            area = Path(temp).resolve()
            package = area / "plugin copy with spaces"
            shutil.copytree(PACKAGE, package)
            before = {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob("*") if p.is_file()}
            server = json.loads((package / "mcp.json").read_text())["mcpServers"]["progress"]
            self.assertEqual(server["type"], "stdio")
            self.assertEqual(server["cwd"], "./")
            cwd = (package / server["cwd"]).resolve()
            self.assertEqual(cwd, package)
            self.assertEqual(server["args"], ["-B", "server.py"])
            commands = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "packaging-test", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "ui://progress/panel.html"}},
            ]
            data_dir = area / "private runtime"
            # The host resolves cwd from its copied plugin, independently of the caller.
            caller = area / "separate caller"; caller.mkdir()
            process = subprocess.run([server["command"], *server["args"], "--data-dir", str(data_dir)], cwd=cwd,
                input="".join(json.dumps(c) + "\n" for c in commands), text=True, capture_output=True, timeout=8)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stderr, "")
            replies = [json.loads(line) for line in process.stdout.splitlines()]
            self.assertEqual([r["id"] for r in replies], [1, 2, 3])
            self.assertEqual(replies[0]["result"]["serverInfo"], {"name": "codex-progress-panel", "version": "0.1.0"})
            self.assertEqual(len(replies[1]["result"]["tools"]), 5)
            reader = next(t for t in replies[1]["result"]["tools"] if t["name"] == "get_progress")
            self.assertEqual(reader["_meta"]["ui"]["visibility"], ["model", "app"])
            self.assertNotIn("resourceUri", reader["_meta"]["ui"])
            self.assertTrue(reader["annotations"]["readOnlyHint"])
            self.assertIn("version:'0.1.0'", replies[2]["result"]["contents"][0]["text"])
            self.assertTrue((data_dir / "progress.sqlite3").is_file())
            self.assertEqual(before, {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob("*") if p.is_file()})
            self.assertFalse(any(caller.iterdir()))


if __name__ == "__main__":
    unittest.main()
