import test from 'node:test';
import assert from 'node:assert/strict';
import { createHomeHistory } from './home-history.mjs';

test('return restores the opened game by identity after cards reorder', () => {
  const memory = createHomeHistory(), viewport = {scrollTop: 0}, focused = [];
  memory.leave(42, 360);
  // Steam briefly focuses the last card while restoring its own route state.
  assert.equal(memory.select(99), false);
  memory.measure(900);
  const handles = new Map([99, 42, 1].map(id => [id, {
    TakeFocus() { focused.push(id); memory.select(id); viewport.scrollTop = 700; return true; },
  }]));
  assert.equal(memory.restore(handles, viewport), true);
  assert.deepEqual(focused, [42]);
  assert.equal(viewport.scrollTop, 360);
  assert.equal(memory.appid, 42);
  assert.equal(memory.pending, null);
  memory.interact();
  assert.equal(memory.select(1), true); // ordinary navigation resumes
});

test('late card registration and inactive navigation do not lose the return target', () => {
  const memory = createHomeHistory(), viewport = {scrollTop: 0};
  memory.leave(42, 360);
  assert.equal(memory.restore(new Map(), viewport), false);
  assert.equal(memory.restore(new Map([[42, {TakeFocus: () => false}]]), viewport), false);
  assert.deepEqual(memory.pending, {appid: 42, scroll: 360});
  assert.equal(memory.restore(new Map([[42, {TakeFocus: () => true}]]), viewport), true);
  assert.equal(viewport.scrollTop, 360);
});

test('return snapshots are consumed once and never pin later navigation', () => {
  const memory = createHomeHistory(), viewport = {scrollTop: 0};
  let calls = 0;
  const handles = new Map([[42, {TakeFocus() { calls++; return true; }}]]);
  memory.leave(42, 120);
  memory.restore(handles, viewport);
  memory.interact();
  memory.select(99); memory.measure(800);
  assert.equal(memory.restore(handles, viewport), false);
  assert.equal(calls, 1);
  assert.equal(memory.appid, 99);
  assert.equal(memory.scroll, 800);
});

test('delayed Steam focus restoration cannot overwrite a successful return', () => {
  const memory = createHomeHistory(), viewport = {scrollTop: 0};
  const handles = new Map([[42, {TakeFocus: () => true}]]);
  memory.leave(42, 360);
  memory.restore(handles, viewport);
  // A later native restoration arrives after our first animation frame.
  viewport.scrollTop = 900;
  memory.measure(900);
  assert.equal(memory.select(99), false);
  assert.equal(memory.appid, 42);
  assert.equal(memory.scroll, 360);
  assert.equal(memory.restore(handles, viewport), true);
  assert.equal(viewport.scrollTop, 360);
  // Directional input before the correction frame starts at the saved card.
  memory.select(99);
  assert.equal(memory.navigationOrigin(99), 42);
  assert.equal(memory.pending, null);
  assert.equal(memory.select(43), true);
  memory.measure(400);
  assert.equal(memory.scroll, 400);
  assert.equal(memory.restore(handles, viewport), false);
});
