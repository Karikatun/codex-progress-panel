# Configuration and storage

The server reads configuration at startup. It keeps local progress state separate from the plugin and package caches. Configuration does not change the root owner or grant task capabilities.

## Select the UI language

The UI uses English by default. It does not select the host or browser language. The supplied title, stages, current work, actor, and blocker keep their original text. Request English task summaries when you want an English example.

To use Russian labels, create `~/.codex-progress-panel/config.json` in the private data directory:

```json
{"language":"ru"}
```

With a custom `--data-dir`, put `config.json` beside `progress.sqlite3`. Use a UTF-8 file no larger than 1024 bytes. The file must be a regular file owned by your OS user. Give it private permissions, such as `0600`. Symlinks, multiple hard links, and group/other permissions are refused. The object accepts only `language` with value `en` or `ru`.

The server reads the file once at startup, before opening SQLite. A missing file selects English. An invalid existing file stops startup with a diagnostic on stderr. The server does not rewrite the file.

Restart the MCP server after changing this configuration. Existing widgets keep their selected language. To override the file, append `--language en` or `--language ru` to the server arguments. This override skips the file entirely, including an invalid file. Task summary language and UI language are independent.

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
npx -y codex-progress-panel@0.2.1 --data-dir /absolute/private/directory --auto-cleanup-finalized
# Full plugin server: python3 -B server.py --data-dir /absolute/private/directory --auto-cleanup-finalized
```

The flag authorizes retention for that directory; it does not change task capabilities or give subagents write access. The server marks `create_progress` with `destructiveHint: true` only while cleanup is enabled. Input and output shapes stay unchanged. Only creation at exactly 128 rows deletes one oldest confirmed finalized execution, ordered by `finalized_at` in UTC, then task id. The deletion and new insert share one SQLite transaction. Duplicate ids, invalid input, corrupt stored state, insert failures, or a full store with no finalized row preserve all history. Unfinished rows, including stale or all-completed snapshots and legacy rows without finalization, are never deleted. Startup, reads, updates and finish do not clean up.

Deletion revokes that execution's tokens. An already frozen widget keeps its confirmed snapshot; reopening the deleted execution is unavailable. Reusing a deleted id creates new tokens; old tokens remain invalid. Removing the flag disables future cleanup and cannot restore deleted history. SQLite reuses freed pages; cleanup does not guarantee a smaller file or bound legacy data volume. It adds one row deletion only on an opted-in creation at capacity.

At capacity with cleanup off or no eligible history, creation gives an actionable error; authenticated reads, updates and finalization still work. Keep text progress until an operator selects a fresh private directory. Preserve the exact old directory first, with the server stopped and explicit authorization. No archive, explicit deletion or history-listing MCP tool is implemented. New writes have a total byte cap because multi-agent text can exceed individual field limits. Older rows remain readable without applying that new cap or rewriting their bytes. Compare-and-swap revisions and SQLite `BEGIN IMMEDIATE` serialize competing writes across processes.
