'use strict';

const assert = require('node:assert/strict');
const { before, after, test } = require('node:test');
const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const crypto = require('node:crypto');

const ROOT = path.resolve(__dirname, '..');
const PACKAGE = path.join(ROOT, 'plugins/progress-panel');
const EXPECTED = ['LICENSE', 'README.md', 'bin/codex-progress-panel.cjs', 'mcp.json', 'package.json', 'panel.html', 'plugin.json', 'server.py', 'skills/progress-panel/SKILL.md'].sort();
let area, tarball, packed, launcher, npmEnv, python, packedBefore;
const running = new Set();

function npmEnvironment(cache) {
  return { ...process.env, npm_config_cache: cache, npm_config_userconfig: path.join(area, 'empty-user.npmrc'),
    npm_config_globalconfig: path.join(area, 'empty-global.npmrc'), npm_config_offline: 'true',
    npm_config_ignore_scripts: 'true', npm_config_audit: 'false', npm_config_fund: 'false', npm_config_update_notifier: 'false' };
}
function treeDigest(root) {
  const entries = [];
  function visit(dir) {
    for (const name of fs.readdirSync(dir).sort()) {
      const file = path.join(dir, name), stat = fs.lstatSync(file);
      assert.ok(!stat.isSymbolicLink(), file);
      if (stat.isDirectory()) visit(file);
      else {
        assert.ok(stat.isFile(), file);
        entries.push([path.relative(root, file), stat.mode & 0o777, crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')]);
      }
    }
  }
  visit(root);
  return entries;
}
function start(command, args, options = {}) {
  const proc = spawn(command, args, { cwd: path.join(area, 'caller with spaces Кириллица'), env: npmEnv, stdio: ['pipe', 'pipe', 'pipe'], ...options });
  running.add(proc);
  const client = { proc, stderr: '', queue: [], waiters: [], seq: 0 };
  proc.stderr.setEncoding('utf8'); proc.stderr.on('data', data => { client.stderr += data; });
  client.exit = new Promise((resolve, reject) => {
    proc.on('error', reject);
    proc.on('close', (code, signal) => { running.delete(proc); resolve({ code, signal }); });
  });
  const lines = readline.createInterface({ input: proc.stdout });
  lines.on('line', line => {
    const waiter = client.waiters.shift();
    if (waiter) waiter(line); else client.queue.push(line);
  });
  client.next = () => new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`MCP reply deadline: ${client.stderr}`)), 8000);
    const accept = line => { clearTimeout(timeout); try { resolve(JSON.parse(line)); } catch (e) { reject(e); } };
    if (client.queue.length) accept(client.queue.shift()); else client.waiters.push(accept);
  });
  client.send = body => proc.stdin.write(JSON.stringify(body) + '\n');
  client.request = async (method, params = {}) => {
    const id = ++client.seq;
    client.send({ jsonrpc: '2.0', id, method, params });
    const reply = await client.next(); assert.equal(reply.id, id); assert.equal(reply.jsonrpc, '2.0'); assert.ok(!reply.error, JSON.stringify(reply.error));
    return reply.result;
  };
  client.call = (name, args) => client.request('tools/call', { name, arguments: args });
  client.initialize = async () => {
    const result = await client.request('initialize', { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'npm-package-test', version: '1' } });
    client.send({ jsonrpc: '2.0', method: 'notifications/initialized' });
    assert.deepEqual(result.serverInfo, { name: 'codex-progress-panel', version: '0.1.1' });
  };
  client.close = async () => { proc.stdin.end(); const result = await deadline(client.exit); assert.deepEqual(result, { code: 0, signal: null }, client.stderr); assert.equal(client.stderr, ''); assert.equal(client.queue.length, 0); };
  return client;
}
async function deadline(promise, ms = 8000) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('process exit deadline')), ms); })]); }
  finally { clearTimeout(timer); }
}
function fromNpm(data, cacheName, options = {}) {
  return start('npm', ['exec', '--offline', '--yes', '--ignore-scripts', `--package=${tarball}`, '--', 'codex-progress-panel', '--data-dir', data],
    { env: npmEnvironment(path.join(area, cacheName)), ...options });
}
function pids() {
  return execFileSync('ps', ['-axo', 'pid=,ppid='], { encoding: 'utf8' }).trim().split('\n').map(line => line.trim().split(/\s+/).map(Number));
}
function descendants(pid) {
  const result = new Set([pid]), rows = pids();
  let more = true;
  while (more) { more = false; for (const [id, parent] of rows) if (result.has(parent) && !result.has(id)) { result.add(id); more = true; } }
  result.delete(pid); return [...result];
}
async function waitGone(ids) {
  const end = Date.now() + 4000;
  while (Date.now() < end) {
    const live = new Set(pids().map(row => row[0]));
    if (ids.every(id => !live.has(id))) return;
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  assert.fail(`owned child processes remained after shutdown: ${ids.join(', ')}`);
}
function fakePython(name, body, mode = 0o755) {
  const dir = path.join(area, name); fs.mkdirSync(dir);
  const file = path.join(dir, 'python3');
  fs.writeFileSync(file, `#!${process.execPath}\n${body}\n`, { mode });
  return dir;
}

before(() => {
  area = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'codex-npm-tests-')));
  fs.mkdirSync(path.join(area, 'caller with spaces Кириллица'));
  fs.writeFileSync(path.join(area, 'empty-user.npmrc'), ''); fs.writeFileSync(path.join(area, 'empty-global.npmrc'), '');
  npmEnv = npmEnvironment(path.join(area, 'pack-cache'));
  python = execFileSync('python3', ['-B', '-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).trim();
  const result = JSON.parse(execFileSync('npm', ['pack', PACKAGE, '--ignore-scripts', '--pack-destination', area, '--json'], { env: npmEnv, cwd: area, encoding: 'utf8', timeout: 15000 }))[0];
  assert.equal(result.name, 'codex-progress-panel'); assert.equal(result.version, '0.1.1');
  assert.deepEqual(result.files.map(file => file.path).sort(), EXPECTED);
  assert.ok(result.size < 100000 && result.unpackedSize < 200000, 'unexpected payload growth');
  tarball = path.join(area, result.filename);
  packed = path.join(area, 'packed root with spaces Юникод'); fs.mkdirSync(packed);
  execFileSync('tar', ['-xzf', tarball, '-C', packed], { timeout: 5000 });
  packed = path.join(packed, 'package'); launcher = path.join(packed, 'bin/codex-progress-panel.cjs');
  packedBefore = treeDigest(packed);
  console.log(`Packed candidate: ${tarball}; sha256=${crypto.createHash('sha256').update(fs.readFileSync(tarball)).digest('hex')}; bytes=${result.size}; unpacked=${result.unpackedSize}`);
});
after(async () => {
  for (const proc of running) { let children = []; try { children = descendants(proc.pid); } catch {} for (const pid of children.reverse()) { try { process.kill(pid, 'SIGKILL'); } catch {} } proc.kill('SIGKILL'); }
  if (packed) assert.deepEqual(treeDigest(packed), packedBefore, 'runtime wrote inside packed package');
  // Optional retention is test evidence only, always outside the repository.
  if (process.env.CODEX_PROGRESS_PANEL_KEEP_TEST_ARTIFACTS !== '1') fs.rmSync(area, { recursive: true, force: true });
});

test('packed payload is a complete ready-to-use plugin and dependency-free npx executable', () => {
  for (const file of EXPECTED) assert.deepEqual(fs.readFileSync(path.join(packed, file)), fs.readFileSync(path.join(PACKAGE, file)), file);
  const metadata = JSON.parse(fs.readFileSync(path.join(packed, 'package.json')));
  assert.equal(metadata.name, 'codex-progress-panel'); assert.equal(metadata.engines.node, '>=22');
  for (const key of ['scripts', 'dependencies', 'optionalDependencies', 'peerDependencies', 'devDependencies', 'bundledDependencies']) assert.equal(metadata[key], undefined);
  assert.deepEqual(metadata.bin, { 'codex-progress-panel': 'bin/codex-progress-panel.cjs' });
  assert.ok(fs.statSync(launcher).mode & 0o111);
  assert.deepEqual(metadata.os, ['darwin', 'linux']);
  const plugin = JSON.parse(fs.readFileSync(path.join(packed, 'plugin.json')));
  assert.equal(plugin.version, metadata.version); assert.equal(plugin.name, metadata.name);
  const source = JSON.parse(fs.readFileSync(path.join(ROOT, 'distribution/marketplace.npm.json'))).plugins[0].source;
  assert.deepEqual(source, { source: 'npm', package: metadata.name, version: metadata.version, registry: 'https://registry.npmjs.org' });
  const config = JSON.parse(fs.readFileSync(path.join(packed, 'mcp.json'))).mcpServers.progress;
  const reply = execFileSync(config.command, [...config.args, '--data-dir', path.join(area, 'full plugin state')],
    { cwd: path.resolve(packed, config.cwd), input: '', encoding: 'utf8', timeout: 8000 });
  assert.equal(reply, '');
});

test('real offline npm exec: stdio, resources, update, freeze and durable restart across two caches', async () => {
  const data = path.join(area, 'persistent state with spaces Данные');
  let client = fromNpm(data, 'first cache with spaces'); await client.initialize();
  const tools = await client.request('tools/list'); assert.equal(tools.tools.length, 5);
  const ui = await client.request('resources/read', { uri: 'ui://progress/panel.html' });
  assert.equal(ui.contents[0].mimeType, 'text/html;profile=mcp-app'); assert.ok(ui.contents[0].text.includes('<!doctype html>')); assert.ok(ui.contents[0].text.includes('<html lang="en">'));
  const fields = { title: 'Packed npm execution', stages: [{ id: 'verify', title: 'Check npm', status: 'running' }] };
  const created = (await client.call('create_progress', { task_id: 'npm-execution-a', ...fields })).structuredContent;
  const opening = { task_id: 'npm-execution-a', read_token: created.read_token };
  const opened = await client.call('open_progress_panel', opening); assert.ok(!JSON.stringify(opened).includes(created.write_token));
  const writing = { task_id: 'npm-execution-a', write_token: created.write_token, ...fields };
  const updated = await client.call('update_progress', { ...writing, expected_revision: 1 }); assert.equal(updated.structuredContent.state.revision, 2);
  const finished = (await client.call('finish_progress', { ...writing, expected_revision: 2 })).structuredContent.state;
  assert.equal(finished.finalized, true); await client.close();
  client = fromNpm(data, 'second relocated cache'); await client.initialize();
  assert.deepEqual((await client.call('get_progress', opening)).structuredContent.state, finished);
  assert.equal((await client.call('update_progress', { ...writing, expected_revision: 3 })).isError, true);
  await client.call('create_progress', { task_id: 'npm-execution-b', ...fields });
  assert.deepEqual((await client.call('get_progress', opening)).structuredContent.state, finished);
  const children = descendants(client.proc.pid); assert.ok(children.length >= 2, 'expected npm launcher and Python child');
  await client.close(); await waitGone(children);
  assert.ok(fs.existsSync(path.join(data, 'progress.sqlite3')));
  for (const cacheName of ['first cache with spaces', 'second relocated cache']) {
    const npxRoot = path.join(area, cacheName, '_npx');
    const roots = fs.readdirSync(npxRoot).map(id => path.join(npxRoot, id, 'node_modules/codex-progress-panel'));
    assert.equal(roots.length, 1);
    assert.deepEqual(treeDigest(roots[0]), packedBefore, 'runtime changed npm cache package bytes');
  }
  assert.equal(fs.readdirSync(path.join(area, 'caller with spaces Кириллица')).length, 0);
});

test('real offline npm exec reads Russian config and forwards an English override without changing finalized state', async () => {
  const data=path.join(area,'configured language');fs.mkdirSync(data,{mode:0o700});
  const config=path.join(data,'config.json');fs.writeFileSync(config,'{"language":"ru"}',{mode:0o600});
  let client=fromNpm(data,'language cache');await client.initialize();
  assert.ok((await client.request('resources/read',{uri:'ui://progress/panel.html'})).contents[0].text.includes('<html lang="ru">'));
  assert.equal((await client.request('resources/list')).resources[0].title,'Этапы задачи');
  const fields={title:'Untranslated title',stages:[{id:'check',title:'Исходный текст',status:'completed'}]};
  const created=(await client.call('create_progress',{task_id:'language-task',...fields})).structuredContent;
  const final=(await client.call('finish_progress',{task_id:'language-task',write_token:created.write_token,expected_revision:1,...fields})).structuredContent.state;
  await client.close();
  client=start('npm',['exec','--offline','--yes','--ignore-scripts',`--package=${tarball}`,'--','codex-progress-panel','--data-dir',data,'--language','en'],{env:npmEnvironment(path.join(area,'language cache'))});
  await client.initialize();assert.ok((await client.request('resources/read',{uri:'ui://progress/panel.html'})).contents[0].text.includes('<html lang="en">'));
  assert.equal((await client.request('resources/list')).resources[0].title,'Task stages');
  assert.deepEqual((await client.call('get_progress',{task_id:'language-task',read_token:created.read_token})).structuredContent.state,final);
  await client.close();assert.equal(fs.readFileSync(config,'utf8'),'{"language":"ru"}');
});

test('packed launcher forwards argument boundaries and preserves child nonzero startup errors', async () => {
  const output = path.join(area, 'recorded arguments.json');
  const fake = fakePython('argument recorder', `const fs=require('node:fs'); fs.writeFileSync(${JSON.stringify(output)}, JSON.stringify(process.argv.slice(2))); process.exit(7);`);
  const args = ['--data-dir', path.join(area, 'quoted " directory $() Кириллица'), 'literal;$(untouched)', '--unknown=value'];
  const proc = start(process.execPath, [launcher, ...args], { env: { ...npmEnv, PATH: fake } });
  assert.deepEqual(await deadline(proc.exit), { code: 7, signal: null });
  const received = JSON.parse(fs.readFileSync(output)); assert.deepEqual(received.slice(4), args); assert.equal(received[0], '-B'); assert.equal(received[1], '-c'); assert.equal(received[3], path.join(packed, 'server.py'));
  assert.equal(proc.queue.length, 0); assert.equal(proc.stderr, '');
  const invalid = start(process.execPath, [launcher, '--data-dir', path.join(area, 'never-created'), '--invalid-option']);
  assert.equal((await deadline(invalid.exit)).code, 2); assert.ok(invalid.stderr.includes('unrecognized arguments')); assert.equal(invalid.queue.length, 0);
  assert.ok(!fs.existsSync(path.join(area, 'never-created')));
});

test('missing, unsupported-version and unexecutable Python fail on stderr without MCP stdout', async () => {
  const empty = path.join(area, 'empty PATH'); fs.mkdirSync(empty);
  const missing = start(process.execPath, [launcher], { env: { ...npmEnv, PATH: empty } });
  assert.equal((await deadline(missing.exit)).code, 1); assert.ok(missing.stderr.includes('not found')); assert.equal(missing.queue.length, 0);
  const old = fakePython('old interpreter simulation', `const cp=require('node:child_process'); const r=cp.spawnSync(${JSON.stringify(python)}, ['-B','-c','import sys; sys.version_info=(3,8); exec(sys.argv[3])',...process.argv.slice(2)], {stdio:'inherit'}); process.exit(r.status);`);
  const unsupported = start(process.execPath, [launcher], { env: { ...npmEnv, PATH: old } });
  assert.equal((await deadline(unsupported.exit)).code, 1); assert.ok(unsupported.stderr.includes('Python 3.9 or newer')); assert.equal(unsupported.queue.length, 0);
  const denied = fakePython('unexecutable interpreter', '', 0o600);
  const blocked = start(process.execPath, [launcher], { env: { ...npmEnv, PATH: denied } });
  assert.equal((await deadline(blocked.exit)).code, 1); assert.ok(blocked.stderr.includes('EACCES')); assert.equal(blocked.queue.length, 0);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  test(`packed launcher ${signal} reaps the real Python server`, async () => {
    const client = start(process.execPath, [launcher, '--data-dir', path.join(area, `signal-${signal}`)]);
    await client.initialize(); const children = descendants(client.proc.pid); assert.equal(children.length, 1);
    client.proc.kill(signal); const exit = await deadline(client.exit); assert.ok([1, 130, 143].includes(exit.code), JSON.stringify(exit));
    await waitGone(children); assert.equal(client.queue.length, 0);
  });
}

async function checkNpmSignal(signal, initialize = client => client.initialize(), options = {}) {
  const terminal = signal === 'SIGINT';
  // npm signals its immediate shell child. Linux sh may wait through a PID-only
  // SIGINT; terminal Ctrl-C reaches the whole foreground process group instead.
  // detached gives this test its own group without signaling the test runner.
  const client = fromNpm(path.join(area, `npm-${signal}`), `signal cache ${signal}`, { ...options, detached: terminal });
  let children = [];
  try {
    await initialize(client); children = descendants(client.proc.pid); assert.ok(children.length >= 2);
    if (terminal) process.kill(-client.proc.pid, signal); else client.proc.kill(signal);
    const exit = await deadline(client.exit);
    assert.ok(exit.signal === signal || [1, 130, 143].includes(exit.code), JSON.stringify(exit));
    await waitGone(children); assert.equal(client.queue.length, 0);
  } catch (error) {
    if (terminal) {
      // This group belongs only to this detached npm client, even when
      // initialization failed before children were recorded or npm already exited.
      try { process.kill(-client.proc.pid, 'SIGKILL'); } catch {}
    } else {
      // Snapshot while npm is still alive, before killing it can reparent children.
      const owned = new Set(children);
      try { for (const pid of descendants(client.proc.pid)) owned.add(pid); }
      catch (cleanupError) { error.cause ??= cleanupError; }
      for (const pid of [...owned].reverse()) { try { process.kill(pid, 'SIGKILL'); } catch {} }
      client.proc.kill('SIGKILL');
    }
    throw error;
  }
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  test(`real offline npm exec ${signal === 'SIGINT' ? 'terminal' : 'wrapper'} ${signal} shuts down its launcher and Python child`, () => checkNpmSignal(signal));
  test(`real offline npm exec ${signal} failed initialization leaves no owned child processes`, async () => {
    const rejection = new Error('client rejected initialized interpreter reply');
    const blocked = fakePython(`blocked initializing interpreter ${signal}`, `
      require('node:readline').createInterface({input:process.stdin}).on('line', line => {
        const request=JSON.parse(line);
        if(request.method==='initialize') console.log(JSON.stringify({jsonrpc:'2.0',id:request.id,result:{serverInfo:{name:'codex-progress-panel',version:'0.1.1'}}}));
      });
      setInterval(()=>{},1000);
    `);
    const options = { env: { ...npmEnvironment(path.join(area, `signal cache ${signal}`)), PATH: blocked + path.delimiter + process.env.PATH } };
    let witness, owned = [], gone = false;
    try {
      await assert.rejects(checkNpmSignal(signal, async client => {
        witness = client;
        await client.initialize();
        owned = descendants(client.proc.pid); assert.ok(owned.length >= 2);
        // Reject at the client boundary before the shutdown helper records children.
        throw rejection;
      }, options), error => error === rejection);
      await waitGone(owned); gone = true;
    } finally {
      // Keep even the deliberately failing regression probe confined to its own tree.
      if (!gone) {
        for (const pid of owned.reverse()) { try { process.kill(pid, 'SIGKILL'); } catch {} }
        if (witness) witness.proc.kill('SIGKILL');
      }
    }
  });
}

test('SIGTERM escalates for an owned child that ignores termination', async () => {
  const stubborn = fakePython('stubborn interpreter', `process.on('SIGTERM',()=>{}); console.log(JSON.stringify({ready:true})); setInterval(()=>{},1000);`);
  const client = start(process.execPath, [launcher], { env: { ...npmEnv, PATH: stubborn } });
  assert.deepEqual(await client.next(), { ready: true }); const children = descendants(client.proc.pid); assert.equal(children.length, 1);
  client.proc.kill('SIGTERM'); assert.equal((await deadline(client.exit, 5000)).code, 1); await waitGone(children);
});

test('explicit help/version work from packed launcher without Python or state', () => {
  const env = { ...npmEnv, PATH: path.join(area, 'empty PATH') };
  assert.equal(execFileSync(process.execPath, [launcher, '--version'], { env, encoding: 'utf8' }), '0.1.1\n');
  const help=execFileSync(process.execPath, [launcher, '--help'], { env, encoding: 'utf8' });
  assert.ok(help.includes('Python 3.9+')); assert.ok(help.includes('--language en|ru')); assert.ok(help.includes('config.json'));
});
