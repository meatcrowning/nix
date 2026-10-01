import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const install = vm.runInNewContext(readFileSync(new URL('./bridge.js', import.meta.url),'utf8') + '\ninstallHomeAudioBridge');
function setup(fail = false) {
  const values = {soundPacks:[{name:'Cube',music:false},{name:'PS2 Ambience',music:true}],
    activeSound:'Default',soundVolume:1,selectedMusic:'None',musicVolume:.5,legacyEnabled:false,
    gamesRunning:[],menuMusic:null};
  const saves=[], music=[], target={};
  const cleanup=install({getPublicState:()=>values,setGlobalState:(k,v)=>values[k]=v},{
    setConfig:async config=>{saves.push(config);return {success:true,result:!fail};},
    changeMenuMusic:(name,old,set)=>{music.push(name);set('menuMusic',name==='None'?null:{volume:values.musicVolume});}
  },target);
  return {values,saves,music,target,cleanup,api:target.SteamHomeAudio};
}
test('settings persist in order, keep ambience optional, and clean up on unload',async()=>{
  const s=setup();
  assert.equal(s.api.read().sound,'Default');assert.equal(s.music.length,0);
  await Promise.all([s.api.write({sound:'Cube'}),s.api.write({soundVolume:.3})]);
  assert.equal(s.saves[1].selected_pack,'Cube');assert.equal(s.saves[1].sound_volume,.3);
  await s.api.write({music:'PS2 Ambience',musicEnabled:true});
  await s.api.write({musicEnabled:false});
  assert.deepEqual(s.music,['PS2 Ambience','None']);
  assert.equal(s.api.read().music,'PS2 Ambience');assert.equal(s.values.menuMusic,null);
  await s.api.write({sound:'Default'});assert.equal(s.api.read().sound,'Default');
  s.cleanup();assert.equal(s.target.SteamHomeAudio,undefined);
});
test('invalid or failed writes never change playback, and the queue recovers',async()=>{
  const s=setup();
  await assert.rejects(s.api.write({sound:'missing'}));
  await assert.rejects(s.api.write({soundVolume:2}));
  assert.equal(s.saves.length,0);assert.equal(s.api.read().sound,'Default');
  await s.api.write({sound:'Cube'});assert.equal(s.api.read().sound,'Cube');
  const f=setup(true);await assert.rejects(f.api.write({music:'PS2 Ambience',musicEnabled:true}));
  assert.equal(f.music.length,0);assert.equal(f.api.read().musicEnabled,false);
});

test('custom effects and music use the encoded Decky asset route; Steam sounds stay native',()=>{
  const url = vm.runInNewContext(readFileSync(new URL('./bridge.js', import.meta.url),'utf8') + '\nhomeAudioURL');
  assert.equal(url('/sounds/deck_ui_navigation.wav'),'/sounds/deck_ui_navigation.wav');
  assert.equal(url('/sounds_custom/PS2 Ambience/menu_music.mp3'),
    'http://127.0.0.1:1337/plugins/Audio%20Loader/assets/sounds/PS2%20Ambience/menu_music.mp3');
  assert.equal(url('/sounds_custom/Test #1/Select.wav'),
    'http://127.0.0.1:1337/plugins/Audio%20Loader/assets/sounds/Test%20%231/Select.wav');
});
