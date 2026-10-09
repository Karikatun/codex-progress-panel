#!/usr/bin/env node
'use strict';

const { spawn } = require('node:child_process');
const path = require('node:path');
const { version } = require('../package.json');

function fail(message) {
  process.stderr.write(`codex-progress-panel: ${message}\n`);
  process.exitCode = 1;
}

const args = process.argv.slice(2);
if (process.platform !== 'darwin' && process.platform !== 'linux') {
  fail('this version supports macOS and Linux only.');
} else if (Number(process.versions.node.split('.')[0]) < 22) {
  fail('Node.js 22 or newer is required.');
} else if (args.length === 1 && args[0] === '--version') {
  process.stdout.write(`${version}\n`);
} else if (args.length === 1 && (args[0] === '--help' || args[0] === '-h')) {
  process.stdout.write(`codex-progress-panel ${version} — stdio MCP server
Usage: codex-progress-panel [--data-dir /absolute/private/directory] [--language en|ru]
Requires macOS/Linux, Node.js 22+, and Python 3.9+ as python3 in PATH.
The default private state directory is ~/.codex-progress-panel.
UI language defaults to English. A private <data-dir>/config.json can set {"language":"ru"}.
--language en|ru overrides and skips that file; language is fixed when the server starts.
All server arguments are forwarded unchanged. No Python download or setup occurs.
`);
} else {
  // Check the interpreter in the same child that runs the server: no probe process,
  // shell expansion, caller-cwd lookup, or stdout banner enters the MCP stream.
  const bootstrap = [
    'import sys',
    'if sys.version_info < (3, 9):',
    '    print("codex-progress-panel: Python 3.9 or newer is required.", file=sys.stderr)',
    '    sys.exit(1)',
    'import runpy',
    'sys.argv = sys.argv[1:]',
    'runpy.run_path(sys.argv[0], run_name="__main__")',
  ].join('\n');
  const child = spawn('python3', ['-B', '-c', bootstrap, path.resolve(__dirname, '../server.py'), ...args], {
    stdio: 'inherit', shell: false,
  });
  let stopping;
  let startupFailed = false;
  let timeout;
  const handlers = {};
  for (const signal of ['SIGINT', 'SIGTERM']) {
    handlers[signal] = () => {
      if (stopping) return;
      stopping = signal;
      child.kill(signal);
      // A blocked child cannot outlive a requested shutdown indefinitely.
      timeout = setTimeout(() => child.kill('SIGKILL'), 2000);
      timeout.unref();
    };
    process.on(signal, handlers[signal]);
  }
  child.on('error', error => {
    startupFailed = true;
    fail(error.code === 'ENOENT'
      ? 'Python 3.9+ was not found. Make python3 available in PATH.'
      : `could not start python3 (${error.code || 'startup error'}).`);
  });
  child.on('close', (code, signal) => {
    clearTimeout(timeout);
    for (const name of Object.keys(handlers)) process.removeListener(name, handlers[name]);
    process.exitCode = startupFailed ? 1 : code === null ? (signal === 'SIGINT' ? 130 : signal === 'SIGTERM' ? 143 : 1) : code;
  });
}
