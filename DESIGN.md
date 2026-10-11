# Progress panel visual direction

Operate mode. Inherit the conversation host's theme, type conventions and quiet utility presentation. A compact ordered stage rail carries status through words and restrained marks; color is supplementary. Current work precedes the list and a real blocker is explicit. Agent rows sit under their owning stage, with wrapped actor, status and current-work text. Four parallel agents must remain legible in a narrow widget.

Show observation separately from stage status. Unfinished snapshots become stale after two minutes even if every stage says completed. Display the last confirmed update time and explain that work may continue. A local timer changes freshness at the boundary; visibility restoration recomputes it. A same-revision read can recover the connection but cannot refresh the timestamp. Failed reads keep the last snapshot and show unavailable/reconnection status. Only confirmed finalization freezes history.

Use polite status announcements for material connection and freshness changes, not each age tick. Keep ordered stages and nested agent lists readable without color. No progress percentage, time estimate or decorative animation. Wrap long text at narrow widths. All supplied task content renders as text. Use system fonts and no remote assets. Native host theme, geometry and screen-reader behavior require separate acceptance checks.

## Plan changes

Keep task and widget identity through authorized scope changes. Reuse keyed stage and agent rows for unchanged ids; reorder existing rows without rebuilding the list. Show only current required stages and a subdued localized “Plan updated” summary above them. Retired-stage evidence stays in the bounded authenticated snapshot. Rename/refinement preserves verified progress; substantial replacement uses fresh stage/assignment ids and confirmed delegation reconciliation. Never infer completion or cancellation from the UI. Finalization keeps the last plan history immutable.

## Storage retention

Keep the 128-row limit. Automatic cleanup is off by default, including the shipped plugin manifest. `--auto-cleanup-finalized` is an explicit same-user operator choice for the exact private data directory. It does not grant task capabilities, list history, or authorize subagent writes. Only `create_progress` at exactly 128 rows can delete one oldest confirmed finalized execution, ordered by timezone-aware `finalized_at` in UTC then id. Incoming validation and duplicate-id rejection precede cleanup. Stored-state validation, selection, one deletion and insertion share the existing `BEGIN IMMEDIATE` transaction; failure rolls back both changes. More than 128 rows fails closed. Unfinished, stale, all-completed but unfinalized, and legacy rows are never eligible. Startup, read, update and finish do not clean up.

Deleted execution capabilities stop working across restart and remain invalid if an id is reused. A frozen widget keeps its confirmed snapshot; reopening a removed row is unavailable. Disabling cleanup cannot restore data. Freed SQLite pages can be reused, but deletion does not guarantee file shrinkage or a volume bound for legacy rows. No timers, maintenance service, archive, VACUUM or extra MCP tool is added.

## Deferred archive and explicit deletion

A future archive/delete flow requires an explicit operator request for exact executions. An online tool must authenticate each selected task's capability; no listing or guessed-id traversal. An offline operator flow can instead use the exact private directory owned by that OS user. Do not combine those authority models silently.

For an offline archive, stop every server using that directory and hold an exclusive maintenance lock. Create a verified private copy before deletion: preserve ownership/permissions and SQLite consistency, reject escaping links/unsafe sidecars, check copy integrity and a restore/read test, and retain a rollback path. Move only explicitly selected finalized records by default; an unfinished record needs a separate exact deletion request. Archive capabilities remain private; moving data does not silently broaden read access. Archive and explicit deletion tools remain deferred.

Acceptance must test concurrent creation/update against maintenance, lock acquisition and interruption recovery on each supported platform, wrong directory/capability rejection, archive failure without deletion, restore byte/state equality, and invalidation of deleted capabilities. Set and test both row-count and data-volume budgets, including database, sidecars and archives. SQLite file size may retain freed pages; deletion alone is not a volume guarantee. These requirements add persistence, authorization and cross-process lock complexity, so that broader maintenance flow remains deferred. At capacity, keep existing reads/writes/finish available and select a fresh private directory only with operator authority and preserved history.
