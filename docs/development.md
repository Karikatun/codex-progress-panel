# Development and acceptance

Run these checks from the repository root. Local, mock, public-distribution and native-host results are separate evidence. The commands below are maintenance instructions, not a claim that every check ran for this documentation update.

## Verify the source

From the repository root, run:

```sh
python3 -B -m unittest discover -s tests -v
node tests/test_bridge.cjs
node --test tests/test_npm.cjs
python3 -B tests/measure_overhead.py
```

Python tests cover real stdio, SQLite, restarts, capability rejection, stale revisions, competing writes, and separate executions. Packaging tests run a copied plugin whose path contains spaces. Bridge tests run the shipped UI script with a DOM/bridge mock. npm tests pack outside the repository and use isolated offline caches. They cover stdout purity, arguments, missing Python, persistent finalization, and shutdown.

Historical evidence recorded in the original documentation: version `0.1.0` passed 48 local tests. Its eight CI matrix jobs passed on macOS/Linux with Node.js 22 and Python 3.9/3.13. Public npx checks for `0.1.0` covered all five tools, the UI resource, freezing, restarts, a second execution, and EOF shutdown.

The local full-plugin flow for `0.1.0` also passed a user-confirmed native two-turn check. That result does not verify every host, accessibility, geometry, or the npm-source full-plugin flow.

## Native acceptance checklist

Use a reviewed `0.2.1` source or package on your target host:

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
13. Record the host version and observations. Native `0.2.1` behavior remains unverified until this check runs.

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
| One observed local run, milliseconds | 5.628 | 4.581 |

Requests used 7,414 fewer bytes (51.0%); responses still contain the full state. The bounded duration covers in-process dispatch, serialization and local SQLite with scenario construction. It excludes process startup, MCP transport, host rendering and UI polls; it is not a latency or speedup benchmark. No token count or dollar estimate is inferred from bytes. UI reads remain separate: a visible unfinished widget polls every 2.5 seconds, with no database mutation. That interval is unchanged. These are local maintenance costs, not host or production measurements.

The same runner measures plan reconciliation against one ordinary full update. In the six-stage example, retiring one confirmed stage and adding one pending stage uses 1,670 request / 2,103 response bytes and 341 bytes of plan metadata. Adding a 42-byte change summary uses 1,741 / 2,145 bytes: 71 extra request bytes and 42 extra response bytes. A semantic patch with a summary uses 342 request bytes and 121 bytes of metadata. Every accepted reconciliation still executes one BEGIN, SELECT, UPDATE and COMMIT, with no extra query, table or row. Confirming affected agents before retirement adds one necessary patch call and UPDATE. Measurements cover local dispatch/serialization/SQLite, not native host behavior.

## Distribution and future releases

Distribute the reviewed source or complete plugin directory with its license. Exclude private databases, sidecars, tokens, logs, environment files, bytecode, caches, local evidence, and `.git`. This repository implies no public plugin-directory submission, signature, or host verification.

Published npm versions cannot be replaced. The source manifests and npm marketplace pin identify `0.2.1`; check [distribution status](installation.md#distribution-status) for public availability. For future package changes, prepare a new version and check package, plugin, and marketplace version agreement. Before publication, pack and review the release artifact outside the repository:

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
