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

Published npm versions cannot be replaced. The source manifests and npm marketplace pin identify `0.2.1`; check [distribution status](installation.md#distribution-status) for public availability. Future package releases pair `codex-progress-panel@VERSION` with Git tag `vVERSION` and a published GitHub Release for the same reviewed source commit. A release is complete only after all three are verified. The providers cannot publish atomically; a partial publication remains incomplete until the missing step is recovered.

### Prepare the release

Prepare a new version for changed package bytes. Check package, plugin, and npm marketplace version agreement, including runtime version strings, tests and versioned documentation. Documentation changes outside the npm payload do not require a new npm version. Run the source checks above and complete the applicable artifact and acceptance review; keep native-host evidence separate.

Use a clean committed source revision on `main`. Record its full commit SHA, verify that remote `main` equals it, and require successful Checks for that exact SHA. Committing, pushing and publication need authority covering those actions; this runbook grants none. For a future release authorized to publish to both npm and GitHub, execute the whole approved sequence without asking again between its covered actions. Stop for a mismatch, missing authority or uncertain result.

Set `version` to the reviewed package version and capture the immutable source identity from the repository root:

```sh
version="$(node -p 'require("./plugins/progress-panel/package.json").version')"
tag="v$version"
source_sha="$(git rev-parse HEAD)"
repo="Karikatun/codex-progress-panel"
git status --porcelain=v1 --untracked-files=all
git ls-remote origin refs/heads/main
```

Confirm the expected repository/remote, no source or control drift, an empty status output and the matching remote SHA before continuing. Capture the version, SHA, check results and artifact identities outside the repository. Before any publication, inspect npm metadata and dist-tags, local and remote tags, and the GitHub Release for this exact version. An absent version/tag/release must be established by a successful provider response; authentication or network errors are not evidence of absence. If an object already exists, use the recovery rules below.

Pack and review the release artifact outside the repository:

```sh
release_dir="$(mktemp -d)"
npm pack ./plugins/progress-panel --ignore-scripts --pack-destination "$release_dir" --json > "$release_dir/pack.json"
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

From `pack.json`, record the exact tarball path, version, size, unpacked size, shasum and integrity. Inspect its contents and compare the unpacked files and modes with the reviewed source. Preserve the tarball and its SHA-256, and prepare reviewed release notes outside the repository. The notes must identify the version and full source SHA, summarize the changes and validation limits, and link to the exact npm version and GitHub source commit. Recheck source and tarball identities before publication. Set `tarball` and `notes_file` to those exact reviewed files; do not use a wildcard or repack after approval.

### Publish the approved version

1. Publish only the reviewed tarball, with the approved stable `latest` dist-tag:

   ```sh
   npm publish "$tarball" --ignore-scripts --access public --tag latest
   ```

   Read back the exact version's registry metadata and npm dist-tags. Check name/version, `dist.shasum` and `dist.integrity` against `pack.json`, and require npm `latest` to equal `version`. Download the registry's exact-version tarball outside the repository; verify its SHA-256 against the retained artifact and compare its unpacked payload and modes with the reviewed source. Record the registry response and the exact npm URL `https://www.npmjs.com/package/codex-progress-panel/v/VERSION`. Test the published exact version in isolation. A successful publish command alone is insufficient.

2. Create the version tag at the recorded commit, then push only that tag:

   ```sh
   git tag -a "$tag" "$source_sha" -m "Release $tag"
   git rev-parse "$tag^{commit}"
   git push origin "refs/tags/$tag:refs/tags/$tag"
   git ls-remote origin "refs/tags/$tag" "refs/tags/$tag^{}"
   ```

   Require the local peeled commit and remote peeled `^{}` SHA to equal `source_sha`. For an existing lightweight tag, its direct remote SHA must equal `source_sha`; for an annotated tag, verify the peeled SHA. Never force, move, delete or overwrite a version tag. Verify the source identity again before creating the Release; the recorded commit, rather than a moving branch, is the release target.

3. Create the GitHub Release using the verified existing remote tag and reviewed notes:

   ```sh
   gh release create "$tag" --repo "$repo" --verify-tag \
     --title "$tag" --notes-file "$notes_file" --latest
   gh release view "$tag" --repo "$repo" \
     --json tagName,targetCommitish,isDraft,isPrerelease,publishedAt,body,url
   gh release view --repo "$repo" --json tagName,url
   ```

   Require `tagName` to equal `tag`, a publication timestamp, `isDraft: false` and `isPrerelease: false`. Check the published body contains the reviewed version, full SHA and exact npm/source links, and verify that GitHub's latest Release is this tag. `targetCommitish` alone does not prove the tag's commit: retain the remote tag verification from step 2. Record the Release URL and recheck npm `latest` before declaring the paired release complete. This stable-release sequence requires the version to be the intended newest stable release; an older version or prerelease needs an explicitly scoped distribution policy instead of changing `latest` by accident.

Test the published exact version's full-plugin native UI in an isolated host before claiming that route is verified. Publication, remote CI, public package behavior and host activation remain separate evidence.

### Recover an incomplete release

After an error, timeout or authentication interruption, read provider state before retrying any write. Do not treat a failed client command as proof that the provider rejected the write, change authentication/settings without authority, force a tag, overwrite a Release or republish an existing npm version.

If npm already contains the approved version, first verify its metadata, artifact/payload and dist-tag as above. Resume only the missing tag or GitHub Release step using the retained source SHA, tarball and notes; never bump or republish merely to repair GitHub. An existing tag must resolve to the approved SHA. An existing Release must pass the version, body, flags and latest checks. A matching existing object satisfies its step without another create command. If a tag or Release exists while npm is absent, verify the GitHub objects first and publish only the missing npm artifact under the original release authority.

If an existing object differs, an artifact is unavailable, a provider read is inconclusive, `latest` has moved to a newer version, or the required source/CI evidence is missing, stop and report the specific mismatch and incomplete state. Resolve it with scoped authority; do not silently replace public history or downgrade a latest pointer. Preserve completed-provider evidence so recovery can finish the same approved version.
