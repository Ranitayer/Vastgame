import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/titlebar.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;

function fixture(reject = false) {
  const document = new EventTarget(), node = new EventTarget(), exports = {};
  node.closest = () => node.excluded ? node : null;
  let calls = 0, errors = 0, clicks = 0;
  vm.runInNewContext(code, { exports, document });
  const action = exports.titlebarDrag(node, {
    start: () => { calls++; return reject ? Promise.reject(new Error('Unavailable')) : Promise.resolve(); },
    onerror: () => errors++,
  });
  node.addEventListener('click', () => clicks++);
  const send = (target, type, overrides = {}) => {
    const event = new Event(type, { cancelable: true });
    Object.assign(event, { button: 0, buttons: 1, isPrimary: true, pointerId: 1, clientX: 10, clientY: 10, detail: 1 }, overrides);
    target.dispatchEvent(event); return event;
  };
  return { node, document, action, send, result: () => ({ calls, errors, clicks }) };
}

test('Click or small movement activates normally; dragging activates native movement once', () => {
  const f = fixture();
  f.send(f.node, 'pointerdown'); f.send(f.document, 'pointermove', { clientX: 12 });
  f.send(f.document, 'pointerup'); f.send(f.node, 'click');
  assert.deepEqual(f.result(), { calls: 0, errors: 0, clicks: 1 });
  f.send(f.node, 'pointerdown'); f.send(f.document, 'pointermove', { clientX: 20 });
  f.send(f.document, 'pointermove', { clientX: 40 }); f.send(f.document, 'pointerup');
  assert.equal(f.send(f.node, 'click').defaultPrevented, true);
  assert.deepEqual(f.result(), { calls: 1, errors: 0, clicks: 1 });
  f.send(f.node, 'pointerdown'); f.send(f.node, 'click');
  assert.equal(f.result().clicks, 2, 'A later normal click must still work');
});

test('Native controls, secondary buttons, unrelated pointers and released gestures never drag', () => {
  const f = fixture();
  f.node.excluded = true; f.send(f.node, 'pointerdown'); f.send(f.document, 'pointermove', { clientX: 30 });
  f.node.excluded = false; f.send(f.node, 'pointerdown', { button: 2 }); f.send(f.document, 'pointermove', { clientX: 30 });
  f.send(f.node, 'pointerdown'); f.send(f.document, 'pointermove', { clientX: 30, pointerId: 2 });
  f.send(f.document, 'pointermove', { clientX: 30, buttons: 0 }); f.send(f.document, 'pointermove', { clientX: 30 });
  assert.equal(f.result().calls, 0);
});

test('Keyboard clicks survive native pointer cancellation; action cleanup removes listeners', () => {
  const f = fixture();
  f.send(f.node, 'pointerdown'); f.send(f.document, 'pointermove', { clientX: 30 });
  f.send(f.document, 'pointercancel'); f.send(f.node, 'click', { detail: 0 });
  assert.deepEqual(f.result(), { calls: 1, errors: 0, clicks: 1 });
  f.action.destroy(); f.send(f.node, 'pointerdown'); f.send(f.document, 'pointermove', { clientX: 30 });
  assert.equal(f.result().calls, 1);
});

test('Native drag failure reports an error without disabling later clicks', async () => {
  const f = fixture(true);
  f.send(f.node, 'pointerdown'); f.send(f.document, 'pointermove', { clientX: 30 });
  await Promise.resolve(); f.send(f.node, 'click');
  assert.deepEqual(f.result(), { calls: 1, errors: 1, clicks: 1 });
});
