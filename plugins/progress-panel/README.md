# codex-progress-panel

A local stdio MCP server and complete Codex plugin for agent-reported task progress. Each assistant execution has its own panel; successful `finish_progress` freezes its final snapshot. The panel does not independently verify code correctness.

Package version: `0.2.0`. See the [main repository](https://github.com/Karikatun/codex-progress-panel) and [Russian introduction](https://github.com/Karikatun/codex-progress-panel/blob/main/README.ru.md).

## Run the standalone MCP server

Use macOS or Linux with Node.js 22+, npm/npx and Python 3.9+ as `python3` in PATH. Windows is unsupported. The launcher has no third-party runtime dependencies, lifecycle scripts or interpreter installer.

```sh
npx -y codex-progress-panel@0.2.0 --help
npx -y codex-progress-panel@0.2.0
```

Configure a stdio MCP server through your host's supported flow:

```json
{"mcpServers":{"progress":{"command":"npx","args":["-y","codex-progress-panel@0.2.0"]}}}
```

The launcher finds its server independently of the caller's directory and preserves server arguments. stdout carries MCP messages; stderr carries diagnostics. It stops on stdin EOF, SIGINT or SIGTERM. It does not install Python or write Codex configuration.

## Complete plugin versus standalone server

The package also includes `plugin.json`, `mcp.json`, `server.py`, `panel.html` and `skills/progress-panel/SKILL.md`. Installing the complete plugin through a reviewed marketplace connects these components together. Its manifest runs Python directly, without the Node launcher.

A standalone MCP entry does not install the skill or activate the complete plugin. The server supplies the HTML resource, but rendering requires an MCP Apps host. Full-plugin use additionally needs local plugins and plugin-relative MCP `cwd`. The host controls placement and accessibility.

Follow the [complete plugin installation guide](https://github.com/Karikatun/codex-progress-panel/blob/main/docs/installation.md) to install from GitHub or local source. Direct GitHub installation was verified with Codex CLI `0.147.0` in an isolated `CODEX_HOME`; native UI remains unverified. The local-source and npm-source full-plugin routes were not tested here. Start a new chat after plugin installation and ask:

> Show the stages of this task in the progress panel and keep them updated as you work.

## Configuration essentials

State lives in `~/.codex-progress-panel/progress.sqlite3`, outside the package and caches. Append `--data-dir /absolute/private/directory` to select another private directory; its parent must exist. Unsafe ownership, permissions, symlinks, hardlinked databases and unsafe SQLite sidecars are refused. State survives server restarts and package removal.

UI labels are English by default. For Russian labels, use `--language ru` or a private `config.json` beside the database containing `{"language":"ru"}`. The file must be UTF-8, at most 1024 bytes, owned by your OS user, with one hard link and private permissions such as `0600`. Invalid configuration stops startup. The language flag skips the file; restart the server after changing configuration. Task text keeps its supplied language.

History is limited to 128 executions. Automatic cleanup is off by default. `--auto-cleanup-finalized` opts in for the selected directory: only creation at capacity deletes one oldest confirmed finalized execution in the same transaction as the new insert. Unfinished or stale executions are never eligible. Deletion revokes their capabilities and cannot be undone; file shrinkage is not guaranteed. Preserve needed history before enabling it.

Only the root owner reports progress and finalizes executions. Keep read/write capabilities private; subagents report to that owner. Completed stages do not prove finalization. Stop or a crash can leave an unfinished snapshot. Stale means no confirmed update for two minutes, not that the agent failed or stopped. Agent summaries do not orchestrate agents, and plan reconciliation does not read conversations automatically.

See [configuration and storage](https://github.com/Karikatun/codex-progress-panel/blob/main/docs/configuration.md), [protocol and recovery](https://github.com/Karikatun/codex-progress-panel/blob/main/docs/protocol.md), and [architecture and security](https://github.com/Karikatun/codex-progress-panel/blob/main/docs/architecture.md). Updates and uninstall instructions are in the [installation guide](https://github.com/Karikatun/codex-progress-panel/blob/main/docs/installation.md#update-and-uninstall). Removing the package preserves private state; archive or delete only the exact data directory with explicit authorization and the server stopped.

## Verification limits

The server has no network listener, transcript access, telemetry, external assets or background daemon. Protocol tests and DOM/bridge mocks do not prove native rendering, Stop/restart behavior or screen-reader access. Native `0.2.0` acceptance remains unverified here; use the [development checklist](https://github.com/Karikatun/codex-progress-panel/blob/main/docs/development.md#native-acceptance-checklist).

[Limitations and deferred features](https://github.com/Karikatun/codex-progress-panel/blob/main/docs/limitations.md) and the technical references are in English.

## License

[MIT](LICENSE), copyright 2026 Karikatun.
