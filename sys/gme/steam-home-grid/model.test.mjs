import { test } from 'node:test';
import assert from 'node:assert/strict';
import { libraryGroups, edgeFades, revealScroll, metadataLine, controllerSupport, displayTitle, adjacentApp, verticalNeighbor } from './model.mjs';
const game = (id, extra = {}) => ({ appid: id, display_name: `Game ${id}`, app_type: 1,
  subscribed_to: true, visible_in_game_list: true,
  per_client_data: [{ clientid: '0', is_available_on_current_platform: true }], ...extra });
test('local games and shortcuts precede owned installable games, without tools or remote-only installs', () => {
  const shortcut = game(7, { app_type: 1073741824, subscribed_to: false });
  const local = game(8, { rt_last_time_played: 100, local_per_client_data: { installed: true } });
  const remote = game(9, { per_client_data: [{ clientid: 'remote', installed: true },
    { clientid: '0', is_available_on_current_platform: true, display_status: 9 }] });
  const groups = libraryGroups([game(1), remote, shortcut, local, local,
    game(2, { app_type: 4 }), game(11, { app_type: 32 }), game(12, { app_type: 2 }),
    game(3, { subscribed_to: false }),
    game(4, { BIsUnreleased: () => true }), game(5, { visible_in_game_list: false }),
    game(6, { local_per_client_data: { is_available_on_current_platform: false } }),
    game(10, { BIsAppBlocked: () => true })]);
  assert.deepEqual(groups.ready.map(a => a.appid), [8, 7]);
  assert.deepEqual(groups.available.map(a => a.appid), [1, 9]);
});
test('fades describe only remaining scrollable content', () => {
  assert.deepEqual(edgeFades(0, 400, 400), { top: false, bottom: false });
  assert.deepEqual(edgeFades(0, 400, 1200), { top: false, bottom: true });
  assert.deepEqual(edgeFades(300, 400, 1200), { top: true, bottom: true });
  assert.deepEqual(edgeFades(800, 400, 1200), { top: true, bottom: false });
});
test('controller focus reveals a whole card without moving an already visible row', () => {
  assert.equal(revealScroll(200, 400, 260, 190), 200);
  assert.equal(revealScroll(200, 400, 100, 190), 78);
  assert.equal(revealScroll(200, 400, 560, 190), 372);
  assert.equal(revealScroll(0, 400, 0, 190), 0);
});

test('component discovery does not trigger Decky React trampoline getters', async () => {
  const { findFocusable } = await import('./steam.mjs');
  let getterReads = 0;
  function unrelated() {}
  Object.defineProperty(unrelated, 'contextType', { get() { getterReads++; throw new Error('React stub installed'); } });
  const native = new Function('e', 'const{"flow-children":t,onActivate:r}=e;return null;');
  const modules = { 1: { unrelated }, 2: { Native: native } };
  const requireModule = id => modules[id];
  requireModule.m = modules;
  assert.equal(findFocusable(requireModule), native);
  assert.equal(getterReads, 0);
});

test('metadata uses console-specific credits and omits unknown shortcut details', () => {
  const app = { BIsShortcut: () => true, rt_original_release_date: 946684800 };
  assert.equal(metadataLine(app, {console: 'GameCube', year: '2002', developer: 'Example'}), '2002 · Example');
  assert.equal(metadataLine({BIsShortcut: () => true}, {console: 'Game Boy Advance'}), '');
  assert.equal(metadataLine({rt_original_release_date: 946684800}), '2000');
  assert.equal(metadataLine(null), '');
});

test('controller badges distinguish full and partial support using Steam capability data', () => {
  assert.equal(controllerSupport(game(1, {store_category: [28]})).level, 'full');
  assert.equal(controllerSupport(game(2, {store_category: [18]})).level, 'partial');
  assert.equal(controllerSupport(game(3, {xbox_controller_support: 2})).level, 'full');
  assert.equal(controllerSupport(game(4, {xbox_controller_support: 1})).level, 'partial');
  assert.equal(controllerSupport(game(5, {store_category: [18, 28]})).level, 'full');
  assert.equal(controllerSupport(game(6, {steam_deck_compat_category: 3, store_category: [29]})), null);
  assert.equal(controllerSupport(undefined), null);
});

test('shortcuts require explicit support metadata, and local corrections override store claims', () => {
  const shortcut = game(1, {app_type: 1073741824, xbox_controller_support: 2});
  assert.equal(controllerSupport(shortcut), null);
  assert.equal(controllerSupport(shortcut, {console: 'PC'}), null);
  assert.equal(controllerSupport(shortcut, {controllerSupport: 'partial'}).level, 'partial');
  assert.equal(controllerSupport(shortcut, {controllerSupport: 'emulated'}).level, 'emulated');
  assert.equal(controllerSupport(game(2, {store_category: [28]}), {controllerSupport: 'none'}), null);
  assert.equal(controllerSupport(shortcut, {controllerSupport: 'unknown'}), null);
});

test('titles lose only console suffixes, not years or editions', () => {
  assert.equal(displayTitle({display_name:'Example (GameCube)'}), 'Example');
  assert.equal(displayTitle({display_name:'Example [PSP]'}), 'Example');
  assert.equal(displayTitle({display_name:'Example (2005)'}), 'Example (2005)');
  assert.equal(displayTitle({display_name:'Example (Special Edition)'}), 'Example (Special Edition)');
});
test('horizontal navigation follows adjacent games across rows and group headings', () => {
  const apps = Array.from({length:25}, (_,i) => ({appid:i+1}));
  assert.equal(adjacentApp(apps,11,1).appid,12);
  assert.equal(adjacentApp(apps,12,-1).appid,11);
  assert.equal(adjacentApp(apps,25,1),undefined);
  assert.equal(adjacentApp(apps,1,-1),undefined);
  assert.equal(adjacentApp(apps,99,1),undefined);
});

test('sort sections group consoles while retaining installed-first ordering', async () => {
  const {librarySections} = await import('./model.mjs');
  const groups = {ready:[game(3), game(1), game(2)], available:[game(4)]};
  const metadata = {1:{console:'PSP'},2:{console:'PC'},3:{console:'PSP'},4:{console:'PC'}};
  const sections = librarySections(groups, metadata, 'console');
  assert.deepEqual(sections.map(s => [s.label,s.apps.map(a=>a.appid)]), [
    ['PC',[2]],['PSP',[1,3]],['PC · Available to install',[4]],
  ]);
  assert.deepEqual(groups.ready.map(a=>a.appid), [3,1,2]);
});
test('release sorting puts unknown dates last in either direction; developer groups use metadata', async () => {
  const {librarySections, validSort} = await import('./model.mjs');
  const groups = {ready:[game(1),game(2),game(3)], available:[]};
  const metadata = {1:{year:'2002',developer:'Studio B'},2:{year:'1995',developer:'Studio A'}};
  const ids = mode => librarySections(groups,metadata,mode).flatMap(s=>s.apps.map(a=>a.appid));
  assert.deepEqual(ids('oldest'),[2,1,3]);
  assert.deepEqual(ids('newest'),[1,2,3]);
  assert.deepEqual(librarySections(groups,metadata,'developer').map(s=>s.label),['Studio A','Studio B','Unknown developer']);
  assert.equal(validSort('bad-value'),'recent');
  assert.equal(validSort('console'),'console');
});

test('vertical navigation keeps the nearest column through short rows and group headings', () => {
  const cards = [{appid:1,top:0,left:0,width:90},{appid:2,top:0,left:100,width:90},
    {appid:3,top:150,left:0,width:90},{appid:4,top:350,left:0,width:90},{appid:5,top:350,left:100,width:90}];
  assert.equal(verticalNeighbor(cards,2,1),3);
  assert.equal(verticalNeighbor(cards,3,1),4);
  assert.equal(verticalNeighbor(cards,5,-1),3);
  assert.equal(verticalNeighbor(cards,1,-1),undefined);
  assert.equal(verticalNeighbor(cards,5,1),undefined);
});
