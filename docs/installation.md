# Installation and removal

The recommended route installs the complete plugin directly from its GitHub marketplace. A local source checkout is available for developers who want to review or change the code. The npm launcher is an alternative for a standalone stdio MCP server. These routes have different host integration requirements.

## Distribution status

The source package and plugin manifests, and the npm-source marketplace pin, identify `0.2.1`. Check the linked public metadata for current package and release availability. Before this release, on 2026-10-12, npm `latest` pointed to `0.2.0` and the public GitHub API listed no tags or Releases. The GitHub marketplace tracks mutable `main`; record and review a commit when you need a fixed source revision.

Sources: [npm metadata](https://registry.npmjs.org/codex-progress-panel), [GitHub tags](https://api.github.com/repos/Karikatun/codex-progress-panel/tags), [GitHub releases](https://api.github.com/repos/Karikatun/codex-progress-panel/releases).

## Recommended: install the full plugin from GitHub

Codex supports GitHub shorthand as a marketplace source. Add this repository, then install its plugin:

```sh
codex plugin marketplace add Karikatun/codex-progress-panel
codex plugin add codex-progress-panel@codex-progress-panel --json
```

The marketplace tracks `main`, so its contents can change. Codex supports `--ref` to select a Git ref when adding the marketplace. For example, `codex plugin marketplace add Karikatun/codex-progress-panel --ref main` selects the current branch. Use a reviewed commit when you need a fixed revision. The command syntax matches Codex CLI `0.147.0` help, and the marketplace and plugin names match the repository manifests.

On 2026-10-12, we tested the GitHub install with Codex CLI `0.147.0` in a fresh isolated home. GitHub `main` resolved to reviewed commit `2915a86a1bf758cbf4b4664430025a81795fec50`. The marketplace and installed plugin matched all 12 reviewed source paths, types, modes and file contents. The test did not change global Codex configuration. This verifies CLI installation only; native desktop rendering remains unverified. Codex CLI `0.147.0` is not a minimum version requirement.

The complete plugin requires macOS or Linux, Python 3.9+ as `python3` in PATH, and a Codex host that supports plugins, plugin-relative MCP `cwd` and MCP Apps UI.

The official OpenAI guide documents [adding a GitHub marketplace and pinning a ref](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli). The repository's marketplace lists the complete plugin, so no separate local configuration is required. Installation and native UI remain unverified on this host.

Start a new chat after installation. If your host requires a restart, preserve running work first.

Example request: **Show the stages of this task in the progress panel and keep them updated as you work.**

## Alternative: install from local source

Use this route if you want to review, test or modify the source before installing. Clone the repository, then add the local marketplace:

```sh
git clone --branch main --single-branch https://github.com/Karikatun/codex-progress-panel.git
cd codex-progress-panel
codex plugin marketplace add "$PWD"
codex plugin add codex-progress-panel@codex-progress-panel --json
```

The plugin manifest runs `python3 -B server.py`. The marketplace commands were checked against Codex CLI `0.147.0`; this is not a minimum version requirement.

The local-source route was not tested here. The direct GitHub route does not need a local checkout or a separate marketplace file. Both routes still require a host that supports plugins, plugin-relative MCP `cwd` and MCP Apps UI.

## Use the npm server

This guide covers `codex-progress-panel@0.2.1`. Check [npm package metadata](https://www.npmjs.com/package/codex-progress-panel) for public availability. The launcher has no third-party runtime dependencies, lifecycle scripts, or interpreter installer. Python handles storage and MCP behavior.

Configure a stdio MCP server in your host:

```json
{"mcpServers":{"progress":{"command":"npx","args":["-y","codex-progress-panel@0.2.1"]}}}
```

Check the launcher requirements:

```sh
npx -y codex-progress-panel@0.2.1 --help
```

To select another state directory, append `--data-dir` and its absolute path as separate arguments. Normal operation sends MCP messages to stdout and diagnostics to stderr. The launcher finds its server independently of the caller's directory. It stops on stdin EOF, SIGINT, or SIGTERM.

This configuration adds only the MCP server. It does not install the `progress-panel` skill or the complete plugin. Use the GitHub marketplace or local-source route for the skill and host integration. The standalone server also supplies the UI resource; an MCP Apps host must render it. The host controls UI rendering.

The standalone `npx` host setup and npm-source full-plugin installation were not tested here.

The npm package also contains the complete plugin. [distribution/marketplace.npm.json](../distribution/marketplace.npm.json) pins its npm source to `0.2.1`. Use that reviewed variant through a host that supports npm marketplace sources. That host needs npm. Full-plugin installation and native UI from the npm source remain unverified.

## Update and uninstall

Review the latest npm release before running the unversioned npx command. Review a newer plugin release before changing its marketplace version pin. Run its tests. Use your host's supported marketplace refresh or reinstallation flow. Preserve the old reviewed package for rollback. Keep runtime state separately. Avoid overwriting a running source tree used by an older absolute-path manifest.

Remove the MCP entry or `codex-progress-panel@codex-progress-panel` through the host's supported removal flow. Remove its marketplace if unused. Removal preserves source files and private state. There is no self-updater or automatic configuration write. npx needs no global installation.

Archive or delete only the exact private data directory with explicit authorization. Stop the server first. Confirm that its history is no longer needed. Do not use broad cleanup commands.
