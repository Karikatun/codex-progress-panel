# codex-progress-panel 0.1.0

A standalone local Codex MCP plugin for explicit progress stages. Each assistant execution gets its own read-only widget. A successful `finish_progress` freezes its final snapshot; later executions cannot overwrite that history.

The server uses Python's standard library and SQLite. It has no network listener, remote assets, transcript access, telemetry, background agent or scheduled task. The skill presents an existing plan and does not replace the project's engineering workflow.

## Requirements

- macOS or Linux, Python 3.9+ available as `python3` in the host's PATH.
- A Codex host that supports local plugins, plugin-relative MCP `cwd`, and MCP Apps UI. Native rendering and exact inline placement must be checked on your host; protocol and mock tests do not establish them.
- Node.js 22+ and npm/npx for the optional npm launcher and test suite. The repository-local full plugin launches Python directly.

Windows is not supported by this version: private-state ownership and permissions use POSIX facilities.

## Install

Clone or download the repository from [GitHub](https://github.com/Karikatun/codex-progress-panel) and review the package before activation. The plugin root is `plugins/progress-panel`; its canonical `plugin.json` and `mcp.json` use the portable Agent Plugins format. The repository marketplace points to that directory. No machine-specific path or variable expansion is required: `cwd: "./"` resolves from the plugin root and launches `python3 -B server.py` from the installed copy.

With a current Codex CLI supporting these commands, run from the repository root:

```sh
codex --version
codex plugin marketplace add "$PWD"
codex plugin add codex-progress-panel@codex-progress-panel --json
codex plugin list --json
```

If your CLI lacks these commands, use the desktop host's supported local marketplace installation flow. Do not edit unrelated configuration to make an older CLI accept it. Start a new chat after installation so it discovers the plugin's skill and tools. A host restart, when required by its installation flow, should wait until running work is safely preserved.

Example request: **«Покажи этапы работы в панели и обновляй её по мере выполнения задачи.»** The skill creates a fresh UUID for each response execution and opens one widget early. Tool calls and intermediate commentary continue that same widget.

## npm/npx distribution

The package name is exactly `codex-progress-panel`, version `0.1.0`. It has no third-party runtime dependencies, lifecycle scripts or interpreter installer. Node 22 is the supported/tested launcher baseline. Python remains the runtime for storage and MCP behavior.

After publication, configure a stdio MCP server with `command: "npx"` and `args: ["-y", "codex-progress-panel@0.1.0"]`. Append `--data-dir` and its absolute path as separate arguments if desired. `npx -y codex-progress-panel@0.1.0 --help` explains the prerequisites. This installs the MCP server path; the full skill/plugin requires a marketplace installation.

`plugins/progress-panel` is also the npm package root. The tarball includes the full plugin, launcher, skill and license through an explicit allowlist. Codex npm plugin installation skips lifecycle/dependency installation, so every required asset ships ready to use. The existing `.agents/plugins/marketplace.json` keeps its local source. The release variant [distribution/marketplace.npm.json](distribution/marketplace.npm.json) pins the same package and version from npm. Supply that reviewed variant through the host's supported marketplace flow after publication; npm is required on that host. Registry installation and native UI through the npm source have not been verified yet.

Package updates or npm cache removal leave `~/.codex-progress-panel` intact. Update the exact version only after reviewing the release; remove the MCP entry/plugin through the host's supported flow. No global installation or automatic configuration write is needed.

## Tools and lifecycle

| Tool | Capability | Effect |
| --- | --- | --- |
| `create_progress` | New explicit execution id | Creates revision 1; returns separate write and read tokens |
| `open_progress_panel` | Read token | Opens that execution's snapshot and passes only the read token to its UI |
| `update_progress` | Write token + expected revision | Atomically replaces the complete snapshot |
| `finish_progress` | Write token + expected revision | Atomically stores and irrevocably freezes the final snapshot |
| `get_progress` | Read token | Reads only that execution; available to the model and UI without rendering another widget |

Create and open once, then update at meaningful milestones. Before the final response, finish with the complete actual snapshot. The display stops polling after observing `finalized: true`, fixes its final timestamp, and ignores later results. Each widget binds to its first execution once. A new user message uses a fresh id and a new widget even when continuing the same project.

Recover a stale update or finish revision through `get_progress` with the retained task id and read token, reconcile with actual work, and retry the intended write once with the returned revision. If already finalized, stop writing. Recovery never calls `open_progress_panel`. If tokens or current-execution tracking are lost, stop panel updates and report the limitation; continue with text progress without creating a replacement execution or another widget in that execution. A failed or unconfirmed finish does not establish a frozen snapshot.

For example, `create_progress` arguments can be:

```json
{
  "task_id": "6e995a7a-4ec4-4a31-a6de-9aab1f30f689",
  "title": "Подготовить изменение",
  "current": "Реализация",
  "actor": "Основной агент",
  "stages": [
    {"id": "build", "title": "Реализовать", "status": "running"},
    {"id": "verify", "title": "Проверить", "status": "pending"}
  ]
}
```

Use the returned read token to open, and the returned write token only in update/finish arguments. Update and finish also require `expected_revision`, `title`, and the complete `stages` array. Never put capabilities, credentials, private source or raw logs in display text.

Finalized means this execution has stopped updating its snapshot. It does not imply all work passed: pending and blocked stages may remain. A blocked stage requires a concrete blocker. Completed implementation, verification, review, publication and deployment are distinct claims. Interruption before successful finish leaves an unfinished snapshot; there is no automatic host-stop detector or hook.

## State and limits

Default data lives in the private `~/.codex-progress-panel/progress.sqlite3`, independently of the package and `CODEX_HOME`. An optional `--data-dir /absolute/private/directory` selects a different directory whose parent already exists. State inside the plugin package or its source marketplace is refused. Existing broad permissions, symlink components, hardlinked database files and unsafe SQLite sidecars are refused. The final directory is created with mode `0700`; the database is private. This version does not migrate or modify the former local plugin's data directory.

State survives restarts. Tokens are random capabilities with no automatic expiry; removing their retained execution state revokes them. Same-user database access and host privileges are outside this capability boundary. There is no listing or token-recovery tool.

The store retains at most **128 executions**, including finalized history, and refuses further creation at capacity. No automatic history eviction is provided. Owners can archive the exact private directory while the server is stopped, then start with a fresh directory. Inputs allow 1–32 stages, titles up to 240 Unicode codepoints, summaries up to 600, and messages up to 64 KiB. Compare-and-swap revisions and SQLite `BEGIN IMMEDIATE` serialize competing writes across processes. Legacy snapshots lacking finalization fields remain readable as unfinished without a write-on-read migration.

While active and visible, the UI reads its bound execution every 2.5 seconds, with a 4-second deadline and retry backoff capped at 15 seconds. Hidden views suspend polling and teardown clears requests/timers. Read failures preserve the last snapshot and report reconnection. Unchanged active snapshots older than two minutes show an age notice that does not claim failure or host stop. An ordinary browser without the MCP Apps bridge reports that the live widget is unavailable.

## Verify and distribute

From the repository root:

```sh
python3 -B -m unittest discover -s tests -v
node tests/test_bridge.cjs
node --test tests/test_npm.cjs
```

Python tests use real stdio, SQLite, restart, unauthorized capabilities, stale revisions, a two-process finish/update race and independent sequential executions. Packaging tests launch a copied plugin directory with spaces from its manifest and isolated temporary state. Node executes the shipped script in a functional DOM/bridge mock. npm tests pack the real allowlisted tarball outside the repository, execute it via offline npm exec in isolated caches, and test stdout purity, argument forwarding, Python prerequisite failures, restart/finalization persistence and process shutdown. These are local protocol and lifecycle checks, not native host, rendered accessibility, geometry, or cross-platform proof. CI is configured for macOS/Linux and Python 3.9/3.13; a workflow file alone does not establish a successful remote run.

Distribute only the reviewed repository source or the complete plugin directory with its license. Exclude `.git`, private databases, SQLite sidecars, capability tokens, environment files, logs, bytecode, caches and local evidence. No public plugin-directory submission, signature or host verification is implied by this repository.

## npm release check (publication requires separate authorization)

Run all checks above. Create the tarball outside the repository and inspect its exact contents, size and integrity before publishing:

```sh
release_dir="$(mktemp -d)"
npm pack ./plugins/progress-panel --ignore-scripts --pack-destination "$release_dir" --json
tar -tzf "$release_dir/codex-progress-panel-0.1.0.tgz"
```

Expected payload: package.json, README.md, LICENSE, bin/codex-progress-panel.cjs, server.py, panel.html, plugin.json, mcp.json and skills/progress-panel/SKILL.md. No databases, sidecars, logs, environment files, caches, tests or repository controls belong in it. The npm tests check this exact closure and execute their own packed artifact with scripts disabled and an isolated offline cache. Preserve the reviewed tarball and its SHA-256 as the release candidate.

Only after explicit publication authorization, publish that exact reviewed tarball with `npm publish /absolute/path/codex-progress-panel-0.1.0.tgz --access public --ignore-scripts`. Publishing, public registry smoke, remote CI, tags and host activation are separate gates; no command in this preparation establishes them. Check package/plugin/marketplace version agreement before each release, then test the published exact version and npm full-plugin native UI in an isolated host.

## Native acceptance before activation is considered verified

On a host with the reviewed candidate installed, use two separate user turns to create executions A and B. Confirm two inline widgets appear in their respective responses. Finish A, then create/update B and read A through `get_progress` without opening another widget: A must retain its final stages and timestamp. Confirm A no longer polls after finalization, including hide/show and delayed replies. Interrupt a third execution before finish and confirm it remains unfinished; automatic interruption detection is not supported. Also check narrow layout, light/dark theme and screen-reader announcements. Record the host version and actual observations. This checklist has not established a native PASS.

## Update and uninstall

Review a newer version and run its tests, then use the host's supported marketplace refresh/reinstallation flow. Preserve the old reviewed package for rollback and keep runtime data separately. Do not overwrite a running source tree if an older local manifest launches it by absolute path. Updates and installation are separate user-authorized actions; no self-updater is included.

Remove `codex-progress-panel@codex-progress-panel` using the host's supported plugin removal flow and remove its marketplace if unused. Plugin removal preserves the standalone source and private data. Archive or remove the exact private data directory only after confirming its history is no longer needed and stopping the server. No broad cleanup command is provided.

## References

Packaging and runtime contract checked 2026-10-09:

- [OpenAI plugin structure](https://developers.openai.com/plugins/build/plugins#plugin-structure): root portable manifest and MCP configuration.
- [OpenAI plugin MCP configuration](https://developers.openai.com/api/docs/guides/agents-api/tools/plugins#authenticate-mcp-servers): relative `cwd` resolves from the plugin root.
- [OpenAI MCP UI](https://developers.openai.com/plugins/build/chatgpt-ui): resource-backed tool UI.
- [OpenAI sidebar apps](https://developers.openai.com/plugins/build/extensions#sidebar-apps): a thread entrypoint requests a sidebar; this package omits it and advertises inline mode. The host still determines placement.
- [MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx): UI initialization, lifecycle, resource and bridge protocol.

[MIT license](LICENSE), copyright 2026 Karikatun.
