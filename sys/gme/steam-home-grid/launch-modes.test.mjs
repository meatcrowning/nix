import test from 'node:test';
import assert from 'node:assert/strict';
import { installLaunchModes, saveLaunchOptions } from './launch-modes.mjs';

function harness({ choose = async () => 1, save, metadata } = {}) {
  const calls = [], errors = [], apps = {RunGame(...args) { calls.push(['run', ...args]); }};
  const original = apps.RunGame;
  const dispose = installLaunchModes({apps, getApp: () => ({appid: 42, BIsShortcut: () => true}),
    metadata: metadata || (async () => ({42: {launchModes: [{label: 'Campaign', options: 'run game --mode campaign'}, {label: 'Zombies', options: 'run game --mode zombies'}]}})),
    choose, save: save || (async (apps, id, options) => calls.push(['save', id, options])),
    reportError: error => errors.push(error.message)});
  return {calls, errors, apps, original, dispose};
}

test('selected mode is saved before launching the same Steam game identity', async () => {
  const h = harness();
  await h.apps.RunGame('180422377472', '', -1, 100);
  assert.deepEqual(h.calls, [['save', 42, 'run game --mode zombies'], ['run', '180422377472', '', -1, 100]]);
  h.dispose(); assert.equal(h.apps.RunGame, h.original);
});

test('cancel and failed saves never launch the default mode', async () => {
  for (const options of [{choose: async () => null}, {save: async () => {throw Error('not saved');}}]) {
    const h = harness(options); await h.apps.RunGame('game');
    assert.equal(h.calls.length, 0); h.dispose();
  }
});

test('repeated Play requests share one chooser; unloading cancels pending launch', async () => {
  let resolve, choices = 0;
  const h = harness({choose: () => { choices++; return new Promise(done => {resolve = done;}); }});
  const launch = h.apps.RunGame('game');
  await Promise.resolve();
  await h.apps.RunGame('game');
  assert.equal(choices, 1);
  h.dispose(); resolve(1); await launch;
  assert.deepEqual(h.calls, []);
});

test('ordinary shortcuts keep their original launch arguments', async () => {
  const h = harness({metadata: async () => ({})});
  await h.apps.RunGame('game', '--example', 3);
  assert.deepEqual(h.calls, [['run', 'game', '--example', 3]]);h.dispose();
});

test('saving waits for Steam acknowledgement and rejects silent failures', async () => {
  let saved, removed = 0;
  const apps = {
    SetShortcutLaunchOptions: async (id, options) => {saved = options;},
    RegisterForAppDetails(id, callback) {callback({strShortcutLaunchOptions: saved});return {unregister(){removed++;}};},
  };
  await saveLaunchOptions(apps, 42, 'run game --mode campaign');assert.equal(removed, 1);
  apps.RegisterForAppDetails = () => ({unregister(){removed++;}});
  await assert.rejects(saveLaunchOptions(apps, 42, 'run game --mode campaign', 5), /did not save/);
  assert.equal(removed, 2);
});
