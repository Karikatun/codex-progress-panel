# codex-progress-panel 0.1.0

A local stdio MCP server and complete Codex plugin for progress snapshots per assistant execution. Python handles private SQLite state, capability tokens, revision checks and frozen final snapshots; the bundled MCP App reads snapshots. The Node launcher starts that same Python server.

Registry commands below become usable after the reviewed 0.1.0 release is published. The local repository installation is available now.

## Requirements and npx server

macOS or Linux; Node.js 22+ and npm/npx; Python 3.9+ available as `python3` in PATH. Windows is unsupported. The launcher downloads no interpreter or dependencies and changes no Codex configuration. Node 22 is the tested CI baseline; the Python server has no third-party dependencies.

After publication, a host's stdio MCP configuration can use:

```json
{"mcpServers":{"progress":{"command":"npx","args":["-y","codex-progress-panel@0.1.0"]}}}
```

The same command can run directly:

```sh
npx -y codex-progress-panel@0.1.0
npx -y codex-progress-panel@0.1.0 --help
```

Normal operation writes only MCP messages to stdout and diagnostics to stderr. It accepts server arguments such as `--data-dir /absolute/private/directory` unchanged, resolves the shipped server independently of the caller directory, and shuts down on stdin EOF, SIGINT or SIGTERM.

## Full Codex plugin

Registering only the MCP server does **not** install the `progress-panel` skill or enable a host's plugin UI flow. This package also contains the complete plugin root: `plugin.json`, `mcp.json`, Python server, HTML UI and `skills/progress-panel/SKILL.md`. The plugin manifest launches Python directly from the installed root. Assets are already present; installation needs no lifecycle script or dependency build.

The repository provides `distribution/marketplace.npm.json` as the npm marketplace release variant. Its entry pins `codex-progress-panel@0.1.0` from the public npm registry. It is usable only after publication and with a Codex host supporting npm marketplace sources; that host needs npm installed. The existing repository-local marketplace continues to use `plugins/progress-panel`.

Use the host's documented marketplace installation flow, then start a new chat. Example request: **«Покажи этапы работы в панели и обновляй её по мере выполнения задачи.»** Native rendering and inline placement depend on the host and need separate acceptance.

## State, updates and removal

State lives in `~/.codex-progress-panel/progress.sqlite3`, outside the npm package/cache and Codex installation. An optional absolute private directory may be selected; its parent must exist. Package-local state, symlinks and unsafe ownership/permissions are refused. Keep tokens and raw logs out of display text.

Review and explicitly pin a newer version when updating the MCP command or marketplace entry. Cache relocation and package removal preserve private state; the launcher has no self-updater. Remove the MCP entry or plugin with the host's supported removal flow. A global installation, if separately chosen, can be removed with `npm uninstall -g codex-progress-panel`; no global installation is required for npx. Archive or delete the exact private directory only with the server stopped and after confirming history is no longer needed.

Each execution gets a separate widget. `finish_progress` freezes its actual final snapshot; pending or blocked stages may remain. Later executions cannot overwrite it. The bounded store retains at most 128 executions and never evicts history automatically.

For complete tools, recovery, limits, verification and native acceptance, see the [repository README](https://github.com/Karikatun/codex-progress-panel#readme). [MIT license](LICENSE), copyright 2026 Karikatun.
