# Installation and removal

The recommended route installs the complete plugin from a reviewed local source checkout. The npm launcher is an alternative for a standalone stdio MCP server. These routes have different host integration requirements.

## Distribution status

Checked on 2026-10-12: the package and plugin manifests are `0.2.0`; the public npm registry contains `0.2.0` and its `latest` tag points to that version. The public GitHub API lists no Git tags or Releases. Use `main` for the source route; it is mutable, not a reproducible version tag. Record and review a commit when you need a fixed source revision. No package was published or release created by this documentation update.

Sources: [npm metadata](https://registry.npmjs.org/codex-progress-panel), [GitHub tags](https://api.github.com/repos/Karikatun/codex-progress-panel/tags), [GitHub releases](https://api.github.com/repos/Karikatun/codex-progress-panel/releases).

## Install the full plugin from local source

Use a reviewed source checkout that contains `.agents/plugins/marketplace.json` and `plugins/progress-panel`. The source manifests identify version `0.2.0`. Use `main`, then review and record its commit before activation.

For a new checkout, select that branch explicitly:

```sh
git clone --branch main --single-branch https://github.com/Karikatun/codex-progress-panel.git
cd codex-progress-panel
```

Review the source before activation. From that checkout's root, run each command:

```sh
codex --version
codex plugin marketplace add "$PWD"
codex plugin add codex-progress-panel@codex-progress-panel --json
codex plugin list --json
```

The command syntax was checked against Codex CLI `0.147.0` help. The marketplace and plugin names match the supplied manifests. This is not an installation or native-host test, and `0.147.0` is not a minimum version requirement. If your CLI lacks these commands, register the marketplace through the supported local flow, open the Plugins Directory, choose the marketplace and install the plugin. The CLI plugin browser is `/plugins`.

Official OpenAI documentation describes [adding a local marketplace](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli), [local plugin installation](https://developers.openai.com/plugins/build/plugins#install-a-local-plugin-manually), and [installing a plugin and starting a new chat](https://learn.chatgpt.com/docs/plugins#install-and-use-a-plugin). These sources establish the supported workflow, not that this plugin was installed or rendered on your host.

Start a new chat after installation. Preserve running work before a restart required by the host.

Example request: **Show the stages of this task in the progress panel and keep them updated as you work.**

The plugin root is `plugins/progress-panel`. It contains portable `plugin.json` and `mcp.json` manifests. The repository marketplace points to that directory. The relative `cwd: "./"` resolves from the installed plugin root. The manifest runs `python3 -B server.py`.

## Use the npm server

This guide covers [`codex-progress-panel@0.2.0`](https://www.npmjs.com/package/codex-progress-panel/v/0.2.0). The launcher has no third-party runtime dependencies, lifecycle scripts, or interpreter installer. Python handles storage and MCP behavior.

Configure a stdio MCP server in your host:

```json
{"mcpServers":{"progress":{"command":"npx","args":["-y","codex-progress-panel@0.2.0"]}}}
```

Check the launcher requirements:

```sh
npx -y codex-progress-panel@0.2.0 --help
```

To select another state directory, append `--data-dir` and its absolute path as separate arguments. Normal operation sends MCP messages to stdout and diagnostics to stderr. The launcher finds its server independently of the caller's directory. It stops on stdin EOF, SIGINT, or SIGTERM.

This configuration adds the MCP server. It does not install the `progress-panel` skill. Use the full plugin route to install the skill and host integration. The standalone server also supplies the UI resource; an MCP Apps host must render it. The host still controls UI rendering.

The npm package also contains the complete plugin. [distribution/marketplace.npm.json](../distribution/marketplace.npm.json) pins its npm source to `0.2.0`. Use that reviewed variant through a host that supports npm marketplace sources. That host needs npm. Full-plugin installation and native UI from the npm source remain unverified.

## Update and uninstall

Review the latest npm release before running the unversioned npx command. Review a newer plugin release before changing its marketplace version pin. Run its tests. Use your host's supported marketplace refresh or reinstallation flow. Preserve the old reviewed package for rollback. Keep runtime state separately. Avoid overwriting a running source tree used by an older absolute-path manifest.

Remove the MCP entry or `codex-progress-panel@codex-progress-panel` through the host's supported removal flow. Remove its marketplace if unused. Removal preserves source files and private state. There is no self-updater or automatic configuration write. npx needs no global installation.

Archive or delete only the exact private data directory with explicit authorization. Stop the server first. Confirm that its history is no longer needed. Do not use broad cleanup commands.
