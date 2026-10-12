# codex-progress-panel

[English](README.md) | [Русский](README.ru.md)

A lightweight progress panel for OpenAI Codex. See what the agent is doing, what it has completed, what remains, and how parallel agents and task requirements change during the work.

![English progress panel](docs/images/progress-panel-en.png)

The current panel component with illustrative English task data. This preview does not prove native Codex rendering or placement.

## Features

- **Task stages:** see pending, active, completed and blocked work.
- **Parallel agents:** see short agent summaries under their stage.
- **Plan changes:** keep the same panel when the agent reconciles changed requirements; retain confirmed progress and retired-stage history.
- **Local persistence:** keep execution state across server restarts.
- **Final snapshots:** successful finalization freezes each execution's history.
- **Freshness:** see the last confirmed update and a stale indication after two minutes without one.
- **Local operation:** no telemetry, network listener, remote assets or background daemon.

The panel displays progress reported by the agent. It does not independently verify that code is correct.

## Install the complete plugin

Use the local-source route to install the skill, MCP server and UI integration together. You need macOS or Linux, Python 3.9+ as `python3` in PATH, and a Codex host that supports local plugins, plugin-relative MCP `cwd` and MCP Apps UI.

Clone the source and review it before activation:

```sh
git clone --branch main --single-branch https://github.com/Karikatun/codex-progress-panel.git
cd codex-progress-panel
```

From the checkout root:

```sh
codex plugin marketplace add "$PWD"
codex plugin add codex-progress-panel@codex-progress-panel --json
codex plugin list --json
```

Start a new chat after installation. If your host requires a restart, preserve running work first. If these CLI commands are unavailable, use the host's local marketplace installation flow.

The command syntax matches Codex CLI `0.147.0` help and the repository manifests; installation and native UI were not tested by this documentation update. See [installation](docs/installation.md) for the official workflow, updating and removal.

Source manifests and the public npm package are `0.2.0`. On 2026-10-12, npm `latest` was `0.2.0`, and GitHub listed no version tags or Releases. `main` is mutable: review and record its commit for a fixed source reference. [Distribution status](docs/installation.md#distribution-status) lists the evidence.

## Start using it

Ask Codex in the new chat:

> Show the stages of this task in the progress panel and keep them updated as you work.

You can refine the active task, for example:

> Add a check for the export format and update the remaining stages.

The root agent reconciles the plan and reports progress. The panel does not read the conversation automatically or orchestrate subagents.

## Standalone MCP server alternative

Use npm/npx when you need the server separately. It requires Node.js 22+, npm/npx and Python 3.9+ on macOS or Linux.

```sh
npx -y codex-progress-panel@0.2.0 --help
```

Add this stdio entry through your host's supported MCP configuration:

```json
{"mcpServers":{"progress":{"command":"npx","args":["-y","codex-progress-panel@0.2.0"]}}}
```

This starts the standalone MCP server. It does not install the `progress-panel` skill or activate the complete plugin. The server supplies an HTML resource, but UI rendering still requires an MCP Apps host. See [standalone installation](docs/installation.md#use-the-npm-server).

## How it works

The complete plugin bundles a skill, a Python standard-library stdio MCP server and an MCP Apps panel. The root agent sends explicit progress summaries; SQLite stores each execution under its own identity and capabilities. The read-only panel displays those summaries and polls for confirmed updates. Successful `finish_progress` freezes the final snapshot; later executions get separate widgets.

## Requirements and limitations

- Windows is unsupported; private storage relies on POSIX ownership and permissions.
- The host controls rendering, placement and accessibility. Native `0.2.0` acceptance remains unverified here; protocol and mock UI tests are separate evidence.
- Completed stages do not prove successful execution finalization. A Stop action or crash before successful finish can leave a snapshot unfinished.
- Stale means no recent confirmed update. It does not prove that the agent failed or stopped.
- State is private and local at `~/.codex-progress-panel/progress.sqlite3`. Automatic cleanup is off by default; history is limited to 128 executions.

English UI labels are the default; Russian labels are configurable. Task summaries keep their supplied language. See [configuration](docs/configuration.md) for language, storage and limits, and [limitations](docs/limitations.md) for unsupported and deferred behavior.

## Documentation

- [Installation](docs/installation.md) — complete plugin, standalone server, updates and removal.
- [Architecture and security](docs/architecture.md) — MCP Apps lifecycle and trust boundaries.
- [Protocol](docs/protocol.md) — tools, revisions, recovery, agents and plan changes.
- [Configuration](docs/configuration.md) — UI language, storage, limits and server flags.
- [Development](docs/development.md) — tests, measured overhead, packaging and native acceptance.
- [Limitations](docs/limitations.md) — supported behavior and deferred proposals.

Technical references are in English. [PRODUCT.md](PRODUCT.md) and [DESIGN.md](DESIGN.md) describe product and design constraints, including proposals that are not implemented.

## License

[MIT](LICENSE), copyright 2026 Karikatun.
