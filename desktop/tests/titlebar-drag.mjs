import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/titlebar.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;

function fixture(reject = false) {
  const document = new EventTarget(), node = new EventTarget(), exports = {};
  node.closest = selector => node.excluded || (node.controlGap && selector.split(',').some(part => part.trim() === '.window-controls')) ? node : null;
  let calls = 0, errors = 0, clicks = 0;
  vm.runInNewContext(code, { exports, document, setTimeout, clearTimeout });
  const action = exports.titlebarDrag(node, {
    start: () => { calls++; return reject ? Promise.reject(new Error('Unavailable')) : Promise.resolve(); },
    onerror: () => errors++,
  });
  node.addEventListener('click', () => clicks++);
  const send = (target, type, overrides = {}) => {
    const event = new Event(type, { cancelable: true });
    Object.assign(event, { button: 0, buttons: 1, clientX: 10, clientY: 10, detail: 1 }, overrides);
    target.dispatchEvent(event); return event;
  };
  return { node, document, action, send, result: () => ({ calls, errors, clicks }) };
}

test('Click or small movement activates normally; dragging activates native movement once', () => {
  const f = fixture();
  f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 12 });
  f.send(f.document, 'mouseup'); f.send(f.node, 'click');
  assert.deepEqual(f.result(), { calls: 0, errors: 0, clicks: 1 });
  f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 20 });
  f.send(f.document, 'mousemove', { clientX: 40 }); f.send(f.document, 'mouseup');
  assert.equal(f.send(f.node, 'click').defaultPrevented, true);
  assert.deepEqual(f.result(), { calls: 1, errors: 0, clicks: 1 });
  f.send(f.node, 'mousedown'); f.send(f.node, 'click');
  assert.equal(f.result().clicks, 2, 'A later normal click must still work');
});

test('Native controls, secondary buttons and released gestures never drag', () => {
  const f = fixture();
  f.node.excluded = true; f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 30 });
  f.node.excluded = false; f.send(f.node, 'mousedown', { button: 2 }); f.send(f.document, 'mousemove', { clientX: 30 });
  f.send(f.node, 'mousedown');
  f.send(f.document, 'mousemove', { clientX: 30, buttons: 0 }); f.send(f.document, 'mousemove', { clientX: 30 });
  assert.equal(f.result().calls, 0);
});

test('Empty space in the window-controls column starts native movement', () => {
  const f = fixture();
  f.node.controlGap = true;
  f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 30 });
  assert.equal(f.result().calls, 1);
});

test('Native cancellation or missed release never swallows the first following click', () => {
  for (const ending of ['pointercancel', 'mousemove']) {
    const f = fixture();
    assert.equal(f.send(f.node, 'mousedown').defaultPrevented, true);
    f.send(f.document, 'mousemove', { clientX: 30 });
    f.send(f.document, ending, { buttons: 0 });
    // Native handoff can consume pointerdown/up; this is the next real click.
    assert.equal(f.send(f.node, 'click').defaultPrevented, false);
    assert.equal(f.result().clicks, 1);
    f.action.destroy();
  }
});

test('The next mouse press works even if native movement consumed every release event', () => {
  const f = fixture();
  f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 30 });
  f.send(f.node, 'mousedown');
  assert.equal(f.send(f.node, 'click').defaultPrevented, false);
  assert.equal(f.result().clicks, 1);
  f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 30 });
  assert.equal(f.result().calls, 2, 'The very next drag must also work');
  f.action.destroy();
});

test('Release click suppression expires even when native movement emits no click', async () => {
  const f = fixture();
  f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 30 });
  f.send(f.document, 'mouseup');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(f.send(f.node, 'click').defaultPrevented, false);
  assert.equal(f.result().clicks, 1);
  f.action.destroy();
});

test('Keyboard clicks survive native pointer cancellation; action cleanup removes listeners', () => {
  const f = fixture();
  f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 30 });
  f.send(f.document, 'pointercancel'); f.send(f.node, 'click', { detail: 0 });
  assert.deepEqual(f.result(), { calls: 1, errors: 0, clicks: 1 });
  f.action.destroy(); f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 30 });
  assert.equal(f.result().calls, 1);
});

test('Native drag failure reports an error without disabling later clicks', async () => {
  const f = fixture(true);
  f.send(f.node, 'mousedown'); f.send(f.document, 'mousemove', { clientX: 30 });
  await Promise.resolve(); f.send(f.node, 'click');
  assert.deepEqual(f.result(), { calls: 1, errors: 1, clicks: 1 });
});
