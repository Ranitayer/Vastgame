import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/session/launch.svelte.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;

for (const failure of [false, true]) {
  test(`Force shutdown cancels an outstanding quote ${failure ? 'failure' : 'success'}`, async () => {
    let release, submitted = 0, quoting;
    const quoteStarted = new Promise(resolve => quoting = resolve);
    const quote = new Promise((resolve, reject) => release = failure ? () => reject(new Error('Offline')) : () => resolve({ quote: { price: 0.2, disk_gb: 60 } }));
    const api = {
      Channel: class {},
      invoke: async command => {
        if (command === 'current_launch') return { session: null };
        if (command === 'quote_game') { quoting(); return quote; }
        if (command === 'launch_game') submitted++;
      },
    };
    const exports = {};
    vm.runInNewContext(code, {
      exports, crypto: { randomUUID }, $state: value => value, setTimeout, clearTimeout,
      require: name => name === '@tauri-apps/api/core' ? api : name === './logs' ? {
        formatLog: message => ({ message }), appendLogs: (before, after) => [...before, ...after],
      } : { phaseLabel: phase => phase },
    });
    const attempt = exports.play({ id: 'fixture', name: 'Fixture', packaged: true, required_disk_gb: 60 }, { id: 1, machine_id: 2, dph_total: 0.2 });
    await quoteStarted;
    exports.beginForceShutdownAll();
    release();
    assert.equal(await attempt, '');
    assert.equal(submitted, 0, 'Cancelled preflight must not rent a replacement VM');
    assert.equal(exports.launch.status, 'stopping', 'Late quote must not overwrite shutdown state');
  });
}
