# Progress panel

<!-- impeccable:product-schema:1 -->

## Product
A local MCP App that shows an existing assistant execution's actual stages while the conversation continues. The root agent supplies explicit short summaries; the panel does not inspect chats, repositories, logs or credentials.

## Audience and task
Russian-speaking engineer observing ongoing work. Success means the current stage, actor and blocker are immediately visible, with completed work kept distinct from verification.

## Platform
web

## Stack
Dependency-free Python 3 stdio MCP server, SQLite state and one self-contained HTML resource. No network backend, external assets, packages or fonts.

## Constraints
Read-only UI, capability-scoped tasks, bounded text and stage count, host bridge polling, honest unavailable and reconnect states, host theme and narrow inline widget layout. Successful finalization freezes history; new executions get separate widgets. Native host rendering is a separate smoke test.
