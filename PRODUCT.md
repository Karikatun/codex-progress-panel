# Progress panel

<!-- impeccable:product-schema:1 -->

## Product
A local MCP App that shows an existing assistant execution's actual stages while the conversation continues. The root agent supplies explicit short summaries and can aggregate several agents under a stage. The panel does not inspect chats, repositories, logs or credentials.

## Audience and task
Engineer observing ongoing work, with English interface labels by default and Russian available through server configuration. Success means the current stage, actor and blocker are immediately visible, with completed work kept distinct from verification.

## Platform
web

## Stack
Dependency-free Python 3 stdio MCP server, SQLite state and one self-contained HTML resource. No network backend, external assets, packages or fonts.

## Constraints
Read-only UI, capability-scoped tasks, bounded text and stage count, host bridge polling, host theme and narrow inline layout. Stage status, observation freshness and finalization are distinct: `live`, `stale`, `finalized` and `unavailable` describe observation, not task outcomes. Stale data includes the last confirmed update time; it never proves that work stopped. Successful finalization freezes history; new executions get separate widgets. One root owner writes through atomic revision checks, using complete snapshots or compact patches. Storage retains 128 executions. Automatic cleanup is off by default; a separate operator flag may replace one oldest confirmed finalized execution only during creation at capacity. Unfinished executions are never removed automatically. Native host rendering is a separate smoke test.

User steering during active work reconciles the same execution and widget. Stable ids and confirmed completion remain; new requirements and re-verification get fresh ids. Server-owned optional plan metadata retains at most 32 exact retired stages inside the existing 64 KiB snapshot. The current UI shows only live required stages and a localized change summary. Affected assignments require confirmed completion/cancellation before retirement; real orchestration and semantic evidence remain root-owner decisions.
