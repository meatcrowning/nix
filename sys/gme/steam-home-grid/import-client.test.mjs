import { test } from 'node:test';
import assert from 'node:assert/strict';
import { importRom } from './import-client.mjs';

const prepared = {slug:'rom-1', title:'Example (NES)', exe:'/bin/games', options:'run rom-1',
  startDir:'/tmp/home', expectedAppId:2147483649, portrait:'image', warning:''};
function harness(existing = [], artFails = false) {
  const calls = [];
  return {calls, deps: {allApps: existing,
    backend: async (action, request) => { calls.push([action, request]); return action === 'prepare' ? prepared : {}; },
    apps: {AddShortcut: async (...args) => { calls.push(['add', ...args]); return 2147483649; },
      SetShortcutStartDir: async (...args) => calls.push(['dir', ...args]),
      SetShortcutLaunchOptions: async (...args) => calls.push(['options', ...args]),
      SetCustomArtworkForApp: async (...args) => { calls.push(['art', ...args]); if (artFails) throw Error('offline'); }},
    refresh: async () => calls.push(['refresh'])}};
}
test('live import records returned Steam ID, applies metadata and portrait, then refreshes', async () => {
  const {calls, deps} = harness();
  const result = await importRom({}, deps);
  assert.equal(result.appid, 2147483649);
  assert.deepEqual(calls.map(c => c[0]), ['prepare','add','finish','dir','options','art','refresh']);
  assert.deepEqual(calls[1], ['add', 'Example (NES)', '"/bin/games"', 'run rom-1', '']);
  assert.deepEqual(calls[2][1], {slug:'rom-1',appid:2147483649});
  assert.equal(calls[5].at(-1), 0);
});
test('retry reuses shortcut and preserves user artwork', async () => {
  const {calls, deps} = harness([{appid:2147483649, display_name:prepared.title, BIsShortcut:()=>true}]);
  await importRom({}, deps);
  assert.deepEqual(calls.map(c=>c[0]), ['prepare','finish','dir','options','refresh']);
});
test('ID collision never overwrites another game', async () => {
  const {calls, deps} = harness([{appid:2147483649, display_name:'Other', BIsShortcut:()=>true}]);
  await assert.rejects(importRom({}, deps), /belongs to another/);
  assert.deepEqual(calls.map(c=>c[0]), ['prepare']);
});
test('artwork failure reports partial success without losing the live ID', async () => {
  const {calls, deps} = harness([], true);
  const result = await importRom({}, deps);
  assert.match(result.warning, /Game added/);
  assert.equal(calls.at(-1)[0], 'refresh');
});
test('invalid native result cannot write metadata for a nonexistent shortcut', async () => {
  const {calls, deps} = harness(); deps.apps.AddShortcut = async () => 0;
  await assert.rejects(importRom({}, deps), /could not add/);
  assert.equal(calls.length, 1);
});

test('retry fills missing artwork without duplicating the shortcut', async () => {
  const {calls, deps} = harness([{appid:2147483649, display_name:prepared.title, BIsShortcut:()=>true}]);
  deps.hasArtwork = () => false;
  await importRom({}, deps);
  assert.ok(calls.some(c=>c[0]==='art'));
  assert.ok(!calls.some(c=>c[0]==='add'));
});
