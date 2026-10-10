# codex-progress-panel 0.1.2

[English](README.md) | [Русский](README.ru.md)

This checkout contains the unpublished `0.1.2` release candidate. It adds reliable stale-state observation, agent summaries, compact patch updates, and explicit opt-in cleanup of finalized history. Publication and native host acceptance remain separate checks.

Show progress stages in a local Codex widget. Each assistant execution gets a new widget. A successful `finish_progress` freezes its final snapshot. Later executions cannot change that history.

The server uses Python's standard library and SQLite. It has no network listener, remote assets, transcript access, telemetry, background agent, or scheduled task. The skill displays an existing plan. The project's instructions and engineering workflow still apply.

## Requirements

| Installation | Requirements |
| --- | --- |
| Full plugin from local source | macOS or Linux; Python 3.9+ as `python3` in PATH |
| npm/npx MCP server | macOS or Linux; Node.js 22+; npm/npx; Python 3.9+ as `python3` in PATH |
| Widget | A Codex host with local plugins, plugin-relative MCP `cwd`, and MCP Apps UI support |

Windows is unsupported. Private state uses POSIX ownership and permissions. Node.js 22 is the tested launcher baseline. The full plugin launches Python directly.

The host controls widget rendering and placement. Check those features on your host. Protocol tests and UI mocks cannot prove native rendering.

## Install the full plugin from local source

Use a reviewed source checkout that contains `.agents/plugins/marketplace.json` and `plugins/progress-panel`. For version `0.1.1`, use source branch `prep/v0.1.1`.

For a new checkout, select that branch explicitly:

```sh
git clone --branch prep/v0.1.1 --single-branch https://github.com/Karikatun/codex-progress-panel.git
cd codex-progress-panel
```

Review the source before activation. From that checkout's root, run each command:

```sh
codex --version
codex plugin marketplace add "$PWD"
codex plugin add codex-progress-panel@codex-progress-panel --json
codex plugin list --json
```

These commands passed with Codex CLI `0.147.0`. This is a verified version, not a minimum version requirement. If your CLI lacks these commands, use your host's supported local marketplace flow.

Start a new chat after installation. Preserve running work before a restart required by the host.

Example request: **«Покажи этапы работы в панели и обновляй её по мере выполнения задачи.»**

The plugin root is `plugins/progress-panel`. It contains portable `plugin.json` and `mcp.json` manifests. The repository marketplace points to that directory. The relative `cwd: "./"` resolves from the installed plugin root. The manifest runs `python3 -B server.py`.

## Use the npm server

This guide covers the unpublished candidate [`codex-progress-panel@0.1.2`](https://www.npmjs.com/package/codex-progress-panel/v/0.1.2). The launcher has no third-party runtime dependencies, lifecycle scripts, or interpreter installer. Python handles storage and MCP behavior.

Configure a stdio MCP server in your host:

```json
{"mcpServers":{"progress":{"command":"npx","args":["-y","codex-progress-panel"]}}}
```

Check the launcher requirements:

```sh
npx -y codex-progress-panel --help
```

To select another state directory, append `--data-dir` and its absolute path as separate arguments. Normal operation sends MCP messages to stdout and diagnostics to stderr. The launcher finds its server independently of the caller's directory. It stops on stdin EOF, SIGINT, or SIGTERM.

This configuration adds the MCP server. It does not install the `progress-panel` skill. Use the full plugin route for the skill and bundled UI resource. The host still controls UI rendering.

The npm package also contains the complete plugin. [distribution/marketplace.npm.json](distribution/marketplace.npm.json) pins its npm source to `0.1.2`. Use that reviewed variant through a host that supports npm marketplace sources. That host needs npm. Public npx server checks for `0.1.0` passed in two fresh caches. Full-plugin installation and native UI from the npm source remain unverified.

Version `0.1.1` adds updated English and Russian documentation. The published `0.1.0` tarball remains unchanged.

## English example

![English progress panel](docs/images/progress-panel-en.png)

The actual panel component shows illustrative English task data. This preview uses the server's default English UI. It does not prove native Codex rendering or placement.

## Select the UI language

The UI uses English by default. It does not select the host or browser language. The supplied title, stages, current work, actor, and blocker keep their original text. Request English task summaries when you want an English example.

To use Russian labels, create `~/.codex-progress-panel/config.json` in the private data directory:

```json
{"language":"ru"}
```

With a custom `--data-dir`, put `config.json` beside `progress.sqlite3`. Use a UTF-8 file no larger than 1024 bytes. The file must be a regular file owned by your OS user. Give it private permissions, such as `0600`. Symlinks, multiple hard links, and group/other permissions are refused. The object accepts only `language` with value `en` or `ru`.

The server reads the file once at startup, before opening SQLite. A missing file selects English. An invalid existing file stops startup with a diagnostic on stderr. The server does not rewrite the file.

Restart the MCP server after changing this configuration. Existing widgets keep their selected language. To override the file, append `--language en` or `--language ru` to the server arguments. This override skips the file entirely, including an invalid file. Task summary language and UI language are independent.

## Tools and execution lifecycle

| Tool | Required capability | Effect |
| --- | --- | --- |
| `create_progress` | New explicit execution id | Creates revision 1 and separate write/read tokens |
| `open_progress_panel` | Read token | Opens one widget and passes only the read token to its UI |
| `update_progress` | Write token and `expected_revision` | Atomically replaces a complete snapshot or merges a patch |
| `finish_progress` | Write token and `expected_revision` | Stores and permanently freezes the complete final snapshot |
| `get_progress` | Read token | Reads that execution without opening another widget |

For each assistant execution:

1. Create a fresh UUID execution id.
2. Retain `{task_id, write_token, read_token, revision, known snapshot}` privately through compaction when available.
3. Open one widget early.
4. Send changed fields at meaningful milestones; retain the returned revision and snapshot.
5. Finish with the actual final snapshot before the final response.

Tool calls, commentary, and context compaction continue the same execution. A new user message starts a new execution and widget. Only the root task owner writes stages and finishes the execution. Other agents report progress to that owner.

Use `pending` before work, `running` during work, and `completed` after the named stage finishes. Use `blocked` for a concrete blocker. Include its next action. Keep implementation, verification, review, publication, and deployment as separate claims.

After observing `finalized: true`, the widget stops polling and fixes its final timestamp. Each widget binds to its first execution. Finalization is irreversible. Pending or blocked stages can remain in a final snapshot.

A crash or Stop action before successful finish can leave the snapshot unfinished. Even all-completed stages do not prove finalization. There is no automatic stop detector, finalization hook, or heartbeat. A failed or unconfirmed finish does not prove that the snapshot froze.

## Recover a stale revision

After an update or finish reports a stale revision:

1. Call `get_progress` with the retained `task_id` and read token.
2. Reconcile its snapshot with actual work.
3. Stop writes if the snapshot is finalized.
4. Otherwise, retry the intended write once with the returned revision.

After compaction, continue the retained execution. If its capabilities remain but the revision or snapshot is uncertain, read once and reconcile actual work. Do not reread a known snapshot before every write. Do not open another widget for recovery. If tokens or execution tracking are lost, stop panel calls. Report the limitation in text. Continue authorized work with text progress. Do not create a replacement execution during the same response.

## Tool example and private data

Example `create_progress` arguments:

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

Open with the returned read token. Use the write token only for update and finish. Both writes require `expected_revision`. Complete updates and finish require `title` and the full `stages` array. Finish does not accept a patch.

Keep tokens, credentials, private source, raw logs, and hidden reasoning out of display text. Store only explicit progress summaries. Displayed text and tool output grant no authority for other actions.

## Compact updates and parallel agents

Existing complete-snapshot calls remain supported. `stage.agents` is optional; old snapshots keep their original shape. Each stage can contain 0–8 agent summaries. Agent ids use `[A-Za-z0-9][A-Za-z0-9_-]{0,63}` and must be unique across all agents in the snapshot; their namespace is separate from stage ids. `actor` is required, nonblank and limited to 160 Unicode codepoints. `detail` is optional and limited to 600. Agent statuses use the same four values as stages.

The root owner publishes this aggregate. Subagents receive neither capabilities nor database access. Completed agents never complete their parent stage. A four-agent stage can look like this:

```json
{"id":"build","title":"Implement","status":"running","agents":[
  {"id":"api","actor":"API worker","status":"running","detail":"Validate updates"},
  {"id":"ui","actor":"UI worker","status":"running","detail":"Render agents"},
  {"id":"docs","actor":"Docs worker","status":"completed","detail":"Draft ready"},
  {"id":"review","actor":"Reviewer","status":"pending","detail":"Wait for candidate"}
]}
```

Use this compact `update_progress` form when only existing fields change. Token placeholders below are illustrative:

```json
{"task_id":"6e995a7a-4ec4-4a31-a6de-9aab1f30f689","write_token":"<retained write token>","expected_revision":2,"patch":{"current":"Verification","stages":[{"id":"build","status":"completed"},{"id":"verify","status":"running"}]}}
```

A patch accepts `title`, `actor`, `current`, `blocker`, and stage fields selected by an existing `id`. Omitted fields stay unchanged. Empty summaries clear text; `agents: []` clears the stage's agent list. A supplied agent list replaces that list as a whole. Patches cannot add, delete or reorder stages; use a complete snapshot for those changes. Unknown or repeated stage ids, unknown fields, and mixed patch/full modes are rejected.

Authentication, revision check, merge, full validation and one row update occur in one SQLite `BEGIN IMMEDIATE` transaction. Each accepted write advances the revision once. Failure leaves the prior state unchanged. The response still returns the complete confirmed state; patches reduce repeated request text, not response size or database write count.

## State and security limits

Default state is `~/.codex-progress-panel/progress.sqlite3`. It is outside `CODEX_HOME`, the package, and package caches. The server creates the final directory with mode `0700` and keeps the database private.

`--data-dir /absolute/private/directory` selects another directory. Its parent must already exist. The server refuses state inside the plugin package or source marketplace. It also refuses unsafe ownership, broad permissions, symlink components, hardlinked database files, and unsafe SQLite sidecars.

State survives server restarts and package removal. Tokens are random capabilities with no automatic expiry. Removing the retained execution state revokes its tokens. Same-user database access and host privileges are outside this boundary. There is no listing or token-recovery tool.

This version does not migrate or modify the former local plugin's data directory. Legacy snapshots without finalization fields remain readable as unfinished. Reading them does not migrate their stored data.

| Limit | Value |
| --- | --- |
| Retained executions, including finalized history | 128; automatic cleanup off by default |
| Stages per snapshot | 1–32 |
| Title | 240 Unicode codepoints |
| Summary | 600 Unicode codepoints |
| Agents per stage | 0–8; unique agent ids across the snapshot |
| Incoming JSON-RPC line | 64 KiB |
| New stored snapshot | 64 KiB compact UTF-8, including server metadata |

Automatic cleanup is off by default, including the plugin manifest. To opt in for the exact private directory you select, add the separate server flag:

```sh
npx -y codex-progress-panel --data-dir /absolute/private/directory --auto-cleanup-finalized
# Full plugin server: python3 -B server.py --data-dir /absolute/private/directory --auto-cleanup-finalized
```

The flag authorizes retention for that directory; it does not change task capabilities or give subagents write access. The server marks `create_progress` with `destructiveHint: true` only while cleanup is enabled. Input and output shapes stay unchanged. Only creation at exactly 128 rows deletes one oldest confirmed finalized execution, ordered by `finalized_at` in UTC, then task id. The deletion and new insert share one SQLite transaction. Duplicate ids, invalid input, corrupt stored state, insert failures, or a full store with no finalized row preserve all history. Unfinished rows, including stale or all-completed snapshots and legacy rows without finalization, are never deleted. Startup, reads, updates and finish do not clean up.

Deletion revokes that execution's tokens. An already frozen widget keeps its confirmed snapshot; reopening the deleted execution is unavailable. Reusing a deleted id creates new tokens; old tokens remain invalid. Removing the flag disables future cleanup and cannot restore deleted history. SQLite reuses freed pages; cleanup does not guarantee a smaller file or bound legacy data volume. It adds one row deletion only on an opted-in creation at capacity.

At capacity with cleanup off or no eligible history, creation gives an actionable error; authenticated reads, updates and finalization still work. Keep text progress until an operator selects a fresh private directory. Preserve the exact old directory first, with the server stopped and explicit authorization. No archive, explicit deletion or history-listing MCP tool is implemented. New writes have a total byte cap because multi-agent text can exceed individual field limits. Older rows remain readable without applying that new cap or rewriting their bytes. Compare-and-swap revisions and SQLite `BEGIN IMMEDIATE` serialize competing writes across processes.

## Widget behavior

The visible active widget polls every 2.5 seconds. Each read has a 4-second deadline. Retry backoff stops increasing at 15 seconds. Hidden views suspend polling. Teardown clears requests and timers.

Observation is `live` before two minutes without a confirmed update, `stale` from that boundary, `finalized` after successful finish, or `unavailable` when reads cannot be obtained. Read failures preserve the last snapshot and show reconnection status. Every unfinished snapshot can become stale, including an all-completed stage list. The UI shows the last confirmed update time. Its local timer and visibility restoration recompute age; same-revision polling does not refresh the snapshot timestamp. Stale does not prove failure or host stop and never changes stages or finalizes them. Without the MCP Apps bridge, an ordinary browser reports that the live widget is unavailable.

## Verify the source

From the repository root, run:

```sh
python3 -B -m unittest discover -s tests -v
node tests/test_bridge.cjs
node --test tests/test_npm.cjs
python3 -B tests/measure_overhead.py
```

Python tests cover real stdio, SQLite, restarts, capability rejection, stale revisions, competing writes, and separate executions. Packaging tests run a copied plugin whose path contains spaces. Bridge tests run the shipped UI script with a DOM/bridge mock. npm tests pack outside the repository and use isolated offline caches. They cover stdout purity, arguments, missing Python, persistent finalization, and shutdown.

Version `0.1.0` passed 48 local tests. Its eight CI matrix jobs passed on macOS/Linux with Node.js 22 and Python 3.9/3.13. Public npx checks for `0.1.0` covered all five tools, the UI resource, freezing, restarts, a second execution, and EOF shutdown.

The local full-plugin flow for `0.1.0` also passed a user-confirmed native two-turn check. That result does not verify every host, accessibility, geometry, or the npm-source full-plugin flow.

## Native acceptance checklist

Use the reviewed candidate on your target host:

1. Create execution A in one user turn.
2. Finish A.
3. Create and update execution B in another user turn.
4. Confirm each response has its own widget.
5. Read A with `get_progress` without opening another widget.
6. Confirm A retains its final stages and timestamp.
7. Confirm A stays frozen after hide/show and delayed replies.
8. Interrupt a third execution before finish.
9. Confirm its snapshot remains unfinished and becomes stale with its original update time.
10. Repeat interruption through process exit; restart the MCP server and reopen the retained execution with its read capability.
11. Check lost connection, hide/show and UI closure without stage changes or implicit finish.
12. Check 1–4 agents, long text, narrow layout, light/dark themes and screen-reader announcements.
13. Record the host version and observations. Candidate native behavior remains unverified until this check runs.

Repeat this check for an npm-source full-plugin installation before claiming that route is verified.

## Measured local overhead

Run `python3 -B tests/measure_overhead.py` for the same six-stage, four-agent execution in full and patch modes. It performs create, open, six milestone updates and finish with equivalent confirmed snapshots. The minimum create/open/finish lifecycle needs three tool calls; no model-side reread is needed when the revision is known.

| Metric | Complete updates | Patch updates |
| --- | ---: | ---: |
| Tool calls | 9 | 9 |
| Request bytes, compact UTF-8 JSON-RPC plus newline | 14,540 | 7,126 |
| Response bytes, same encoding | 17,034 | 17,034 |
| SQL mutations | 1 INSERT + 7 UPDATE | 1 INSERT + 7 UPDATE |
| Retained rows / final revision | 1 / 8 | 1 / 8 |
| Final stored state / SQLite file bytes | 1,784 / 12,288 | 1,784 / 12,288 |
| One observed local run, milliseconds | 4.336 | 4.523 |

Requests used 7,414 fewer bytes (51.0%); responses still contain the full state. The bounded duration covers in-process dispatch, serialization and local SQLite with scenario construction. It excludes process startup, MCP transport, host rendering and UI polls; it is not a latency or speedup benchmark. No token count or dollar estimate is inferred from bytes. UI reads remain separate: a visible unfinished widget polls every 2.5 seconds, with no database mutation. That interval is unchanged. These are local maintenance costs, not host or production measurements.

## Optional lifecycle adapter: proposed, not installed

Official [hooks documentation](https://learn.chatgpt.com/docs/hooks) supports reviewed hooks that call an already-connected MCP server. MCP hooks run synchronously, skip tool approvals, and do not start or reconnect the server. `SessionEnd` does not support MCP hooks. `Stop` can continue a turn; it is not proof of completed work. Hooks have repeats, coverage gaps and specialized tool paths. The [plugin guide](https://developers.openai.com/plugins/build/plugins) supports lifecycle hooks for manually installed desktop plugins, requires trust review, and excludes hook-bearing plugins from the public plugin directory. These are current documentation findings, not a tested integration.

A future opt-in pilot can observe activity only. It must use an explicit private registration from session/turn ids to this execution's capability; ids alone grant no access. Allowlist event kind, bounded session/turn/tool/agent identifiers and an observation timestamp. Discard prompts, tool inputs/outputs, transcripts, transcript paths, raw logs and capabilities from event/display data. Registration must keep the root as the only progress writer. Never refresh confirmed progress time, infer stage results or auto-finalize from activity. Use a short fixed timeout, bounded deduplication and rate limits, fail open without model context or blocking decisions, and preserve explicit progress calls as the fallback. Test missing connection, repeats, gaps, compaction and interrupt before activation.

The [notify configuration](https://learn.chatgpt.com/docs/config-file/config-advanced) supplies `agent-turn-complete` only. The [app-server documentation](https://learn.chatgpt.com/docs/app-server) describes notifications for clients; its command and WebSocket transport are experimental and unsupported for production. It does not establish a plugin-native event subscription for this widget. No private-log parsing, undocumented events or monkey-patching is proposed.

Linked executions are also deferred. An id link alone cannot grant capability-safe traversal. Any future explicit link must preserve per-execution read authorization and immutable history, with no global registry, state merge or automatic project discovery.

## Distribution and future releases

Distribute the reviewed source or complete plugin directory with its license. Exclude private databases, sidecars, tokens, logs, environment files, bytecode, caches, local evidence, and `.git`. This repository implies no public plugin-directory submission, signature, or host verification.

Published npm version `0.1.0` cannot be replaced. Prepare a new version for changed package bytes. Check package, plugin, and marketplace version agreement for that release. Publication requires separate authorization.

After choosing the next version, pack the candidate outside the repository:

```sh
release_dir="$(mktemp -d)"
npm pack ./plugins/progress-panel --ignore-scripts --pack-destination "$release_dir" --json
```

Inspect the resulting tarball's contents, size, and integrity. Its payload must contain exactly these nine files:

```text
package.json
README.md
LICENSE
bin/codex-progress-panel.cjs
server.py
panel.html
plugin.json
mcp.json
skills/progress-panel/SKILL.md
```

Preserve the reviewed tarball and SHA-256. Only publish that exact artifact after authorization. Public registry checks, tags, remote CI, and host activation require separate evidence. Test the published exact version and its full-plugin native UI in an isolated host.

## Update and uninstall

Review the latest npm release before running the unversioned npx command. Review a newer plugin release before changing its marketplace version pin. Run its tests. Use your host's supported marketplace refresh or reinstallation flow. Preserve the old reviewed package for rollback. Keep runtime state separately. Avoid overwriting a running source tree used by an older absolute-path manifest.

Remove the MCP entry or `codex-progress-panel@codex-progress-panel` through the host's supported removal flow. Remove its marketplace if unused. Removal preserves source files and private state. There is no self-updater or automatic configuration write. npx needs no global installation.

Archive or delete only the exact private data directory with explicit authorization. Stop the server first. Confirm that its history is no longer needed. Do not use broad cleanup commands.

## References

- [OpenAI plugin structure](https://developers.openai.com/plugins/build/plugins#plugin-structure)
- [OpenAI plugin MCP configuration](https://developers.openai.com/api/docs/guides/agents-api/tools/plugins#authenticate-mcp-servers)
- [OpenAI MCP UI](https://developers.openai.com/plugins/build/chatgpt-ui)
- [MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)

[MIT license](LICENSE), copyright 2026 Karikatun.
