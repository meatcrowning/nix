import { test } from 'node:test';
import assert from 'node:assert/strict';
import { importRom, verifyShortcut } from './import-client.mjs';

const prepared = {slug:'rom-1', title:'Example (NES)', exe:'/bin/games', options:'run rom-1',
  startDir:'/tmp/home', expectedAppId:2147483649, artwork:[
    {type:0,label:'Box art',extension:'png',data:'cover'},
    {type:1,label:'Background artwork',extension:'png',data:'hero'}], warning:''};
function harness(existing = [], artFails = false) {
  const calls = [], details = {};
  const deps = {allApps: existing,
    backend: async (action, request) => { calls.push([action, request]); return action === 'prepare' ? prepared : {}; },
    apps: {
      // Reproduce Steam's real behavior: wraps the executable, initially derives
      // the display name from its basename, and returns before configuration.
      AddShortcut: async (...args) => {
        calls.push(['add', ...args]);details.strShortcutExe=`"${args[1]}"`;details.strDisplayName='games';return 2147483649;
      },
      SetShortcutName: async (_,value) => {calls.push(['name',value]);details.strDisplayName=value;},
      SetShortcutExe: async (_,value) => {calls.push(['exe',value]);details.strShortcutExe=value;},
      SetShortcutStartDir: async (_,value) => {calls.push(['dir',value]);details.strShortcutStartDir=value;},
      SetShortcutLaunchOptions: async (_,value) => {calls.push(['options',value]);details.strShortcutLaunchOptions=value;},
      RegisterForAppDetails: (_,callback) => {calls.push(['verify']);callback(details);return {unregister(){calls.push(['unregister']);}};},
      SetCustomArtworkForApp: async (...args) => { calls.push(['art', ...args]); if (artFails) throw Error('offline'); }
    },
    refresh: async () => calls.push(['refresh'])};
  return {calls,details,deps};
}
test('realistic Steam name/quoting behavior is corrected and verified before success', async () => {
  const {calls, details, deps} = harness();
  const result = await importRom({}, deps);
  assert.equal(result.appid, 2147483649);
  assert.deepEqual(calls.find(c=>c[0]==='add'), ['add', 'Example (NES)', '/bin/games', '', '']);
  assert.equal(details.strShortcutExe,'"/bin/games"');
  assert.equal(details.strDisplayName,prepared.title);
  const names=calls.map(c=>c[0]);
  assert.ok(names.indexOf('record')<names.indexOf('verify'));
  assert.ok(names.indexOf('verify')<names.indexOf('finish'));
  assert.deepEqual(calls.filter(c=>c[0]==='art').map(c=>c.at(-1)),[0,1]);
  assert.equal(names.at(-1),'refresh');
});
test('retry reuses shortcut and preserves existing user artwork', async () => {
  const {calls, deps} = harness([{appid:2147483649, display_name:prepared.title, BIsShortcut:()=>true}]);
  await importRom({}, deps);
  assert.ok(!calls.some(c=>['add','art'].includes(c[0])));
  assert.ok(calls.some(c=>c[0]==='verify'));
});
test('ID collision never overwrites another game', async () => {
  const {calls, deps} = harness([{appid:2147483649, display_name:'Other', BIsShortcut:()=>true}]);
  await assert.rejects(importRom({}, deps), /belongs to another/);
  assert.deepEqual(calls.map(c=>c[0]), ['prepare']);
});
test('artwork failure is reported explicitly after a verified shortcut', async () => {
  const {calls, deps} = harness([], true);
  const result = await importRom({}, deps);
  assert.match(result.warning, /Box art could not be applied/);
  assert.match(result.warning, /Background artwork could not be applied/);
  assert.equal(calls.at(-1)[0], 'refresh');
});
test('invalid native result cannot write metadata for a nonexistent shortcut', async () => {
  const {calls, deps} = harness(); deps.apps.AddShortcut = async () => 0;
  await assert.rejects(importRom({}, deps), /could not add/);
  assert.equal(calls.length, 1);
});
test('retry fills a missing hero without overwriting the existing cover', async () => {
  const {calls, deps} = harness([{appid:2147483649, display_name:prepared.title, BIsShortcut:()=>true}]);
  deps.hasArtwork = (_, type) => type === 0;
  await importRom({}, deps);
  assert.deepEqual(calls.filter(c=>c[0]==='art').map(c=>c.at(-1)),[1]);
  assert.ok(!calls.some(c=>c[0]==='add'));
});
test('setter rejection leaves a retryable ID but never reports completion', async () => {
  const {calls, deps} = harness();deps.apps.SetShortcutName=async()=>{throw Error('setter failed');};
  await assert.rejects(importRom({}, deps), /setter failed/);
  assert.ok(calls.some(c=>c[0]==='record'));
  assert.ok(!calls.some(c=>c[0]==='finish'));
});
test('silent Steam corruption times out instead of producing false success', async () => {
  const {calls, deps} = harness();deps.apps.SetShortcutName=async()=>{};
  deps.verify=(apps,id,expected)=>verifyShortcut(apps,id,expected,10);
  await assert.rejects(importRom({}, deps), /did not save/);
  assert.ok(!calls.some(c=>c[0]==='finish'));
  assert.equal(calls.filter(c=>c[0]==='unregister').length,1);
});
test('verification waits for native updates and rejects double-quoted paths', async () => {
  let notify,closed=0;
  const apps={RegisterForAppDetails:(_,callback)=>{notify=callback;return {unregister(){closed++;}};}};
  const pending=verifyShortcut(apps,42,prepared,100);
  notify({strDisplayName:'games'});
  notify({strDisplayName:prepared.title,strShortcutExe:'"/bin/games"',strShortcutStartDir:'"/tmp/home"',strShortcutLaunchOptions:prepared.options});
  await pending;assert.equal(closed,1);
  const bad=verifyShortcut(apps,42,prepared,10);
  notify({strDisplayName:prepared.title,strShortcutExe:'""/bin/games""',strShortcutStartDir:'"/tmp/home"',strShortcutLaunchOptions:prepared.options});
  await assert.rejects(bad,/did not save/);assert.equal(closed,2);
});
