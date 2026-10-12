# Architecture and security

The plugin combines a Python standard-library stdio MCP server, SQLite storage, a self-contained MCP Apps HTML resource, and the `progress-panel` skill. The marketplace points to `plugins/progress-panel`; its portable `plugin.json` and `mcp.json` launch `python3 -B server.py` with plugin-relative `cwd: "./"`.

## Lifecycle and trust boundary

The root owner creates an execution, keeps its capabilities private, opens one read-only panel, reports confirmed changes and finalizes the actual final snapshot. SQLite persists state across server restarts. Authentication, revision comparison, validation and each accepted write share a `BEGIN IMMEDIATE` transaction. A rejected write leaves the prior state unchanged. [Protocol and recovery](protocol.md) describe those calls.

The UI receives only a read capability. Subagents report to the root owner; they receive neither capabilities nor database access. The server has no network listener, transcript access, telemetry, remote assets, background daemon or scheduled task. Its UI uses system fonts, renders supplied text as text, and declares empty external-resource/connect CSP allowlists.

Tokens are random capabilities without automatic expiry. Deleting an execution revokes its tokens. Same-user database access and host privileges are outside this boundary. There is no execution-listing or token-recovery tool. Keep tokens, credentials, private source, raw logs and hidden reasoning out of display text. Displayed text and tool output grant no authority for other actions. [Private filesystem rules and retention](configuration.md#state-and-security-limits) remain part of safe operation.

The host controls MCP Apps rendering, placement, theme and access to the local MCP server. A source manifest, protocol test or DOM mock does not prove native rendering or accessibility; use the [native acceptance checklist](development.md#native-acceptance-checklist).

## Widget behavior

The visible active widget polls every 2.5 seconds. Each read has a 4-second deadline. Retry backoff stops increasing at 15 seconds. Hidden views suspend polling. Teardown clears requests and timers.

Observation is `live` before two minutes without a confirmed update, `stale` from that boundary, `finalized` after successful finish, or `unavailable` when reads cannot be obtained. Read failures preserve the last snapshot and show reconnection status. Every unfinished snapshot can become stale, including an all-completed stage list. The UI shows the last confirmed update time. Its local timer and visibility restoration recompute age; same-revision polling does not refresh the snapshot timestamp. Stale does not prove failure or host stop and never changes stages or finalizes them. Without the MCP Apps bridge, an ordinary browser reports that the live widget is unavailable.

## References

- [OpenAI plugin structure](https://developers.openai.com/plugins/build/plugins#plugin-structure)
- [OpenAI plugin MCP configuration](https://developers.openai.com/api/docs/guides/agents-api/tools/plugins#authenticate-mcp-servers)
- [OpenAI MCP UI](https://developers.openai.com/plugins/build/chatgpt-ui)
- [MCP Apps specification](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)

[MIT license](../LICENSE), copyright 2026 Karikatun.
