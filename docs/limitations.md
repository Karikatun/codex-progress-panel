# Limitations and deferred features

## What the panel does and does not establish

- The panel displays agent-reported progress. It does not independently verify code correctness or monitor every Codex action.
- A completed stage is a work status. Only successful `finish_progress` finalizes the execution; final snapshots can retain pending or blocked stages.
- Stale means no confirmed update for two minutes. Work may continue; stale does not prove a failed or stopped agent.
- A standalone MCP server entry does not install the plugin skill or activate native UI integration. Its server still supplies the HTML resource to an MCP Apps host.
- Plan reconciliation uses explicit updates from the root owner after authorized user steering. It does not read conversations automatically.
- Agent summaries report assignments. They do not launch, cancel or otherwise orchestrate subagents.
- Protocol and DOM/bridge tests do not prove native host rendering, interruption behavior, geometry or screen-reader access. Native `0.2.1` acceptance remains unverified here.

## Supported environment

Use macOS or Linux with Python 3.9+ as `python3` in PATH. The npm launcher additionally requires Node.js 22+ and npm/npx. Windows is unsupported because private storage relies on POSIX ownership and permissions. The UI needs a host with MCP Apps support; full-plugin use also needs local plugins and plugin-relative MCP `cwd`. An ordinary browser without the MCP Apps bridge cannot provide live updates.

There is no automatic stop detector, finalization hook or heartbeat. A crash, Stop action or failed finish can leave the execution unfinished. Lost capabilities require text progress, not a replacement execution during the same response. There is no implemented archive, explicit deletion, execution-listing, token-recovery or linked-execution tool. See [configuration](configuration.md) for capacity and opt-in finalized-history cleanup.

## Deferred work

Lifecycle activity integration, linked executions, archive and explicit deletion remain proposals. The [design document](../DESIGN.md#deferred-archive-and-explicit-deletion) retains archive requirements; it does not describe an installed feature.

## Optional lifecycle adapter: proposed, not installed

Official [hooks documentation](https://learn.chatgpt.com/docs/hooks) supports reviewed hooks that call an already-connected MCP server. MCP hooks run synchronously, skip tool approvals, and do not start or reconnect the server. `SessionEnd` does not support MCP hooks. `Stop` can continue a turn; it is not proof of completed work. Hooks have repeats, coverage gaps and specialized tool paths. The [plugin guide](https://developers.openai.com/plugins/build/plugins) supports lifecycle hooks for manually installed desktop plugins, requires trust review, and excludes hook-bearing plugins from the public plugin directory. These are current documentation findings, not a tested integration.

A future opt-in pilot can observe activity only. It must use an explicit private registration from session/turn ids to this execution's capability; ids alone grant no access. Allowlist event kind, bounded session/turn/tool/agent identifiers and an observation timestamp. Discard prompts, tool inputs/outputs, transcripts, transcript paths, raw logs and capabilities from event/display data. Registration must keep the root as the only progress writer. Never refresh confirmed progress time, infer stage results or auto-finalize from activity. Use a short fixed timeout, bounded deduplication and rate limits, fail open without model context or blocking decisions, and preserve explicit progress calls as the fallback. Test missing connection, repeats, gaps, compaction and interrupt before activation.

The [notify configuration](https://learn.chatgpt.com/docs/config-file/config-advanced) supplies `agent-turn-complete` only. The [app-server documentation](https://learn.chatgpt.com/docs/app-server) describes notifications for clients; its command and WebSocket transport are experimental and unsupported for production. It does not establish a plugin-native event subscription for this widget. No private-log parsing, undocumented events or monkey-patching is proposed.

Linked executions are also deferred. An id link alone cannot grant capability-safe traversal. Any future explicit link must preserve per-execution read authorization and immutable history, with no global registry, state merge or automatic project discovery.
