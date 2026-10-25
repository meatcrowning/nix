// Pure protocol tests: no browser windows, system services, or input devices.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let tick, wire, sent = [], executed = [], removed;
let enabled = true, visible = true;
const event = {addListener() {}};
const context = {vivaldiWindowId:42, document:{title:'Example'}};
const sandbox = {
    console, setInterval(fn) { tick = fn; }, setTimeout() {},
    WebSocket: class {
        static OPEN = 1; readyState = 1;
        constructor() { wire = this; }
        send(text) { sent.push(JSON.parse(text)); }
    },
    vivaldi:{menuContent:{get(_name, cb) { cb(1, 'horizontal', []); }, onChanged:event}},
    chrome:{bookmarks:{getTree(cb) { cb([]); }}, windows:{onRemoved:{addListener(fn) {removed=fn;}}}},
};
vm.runInNewContext(fs.readFileSync(require.resolve('../vivaldi-global-menu.js'), 'utf8'), sandbox);
const utils = {getShortcutSettings(){return {};}, isSeparator(){return false;},
    getDisplayName(item){return item.label;}, getShortcut(){return {value:'Ctrl+T'};}};
const store = {makeMenuWithContent(){return [{label:'File',items:[
    {label:'New Tab',commandName:'NEW',isEnabled:()=>enabled,isVisible:()=>visible},
    {label:'Disabled folder',isEnabled:()=>false,items:[{label:'Hidden action',commandName:'CHILD'}]},
]}];}};
sandbox.desktopVivaldiMenu(context,(...args)=>executed.push(args),store,utils,{type:'normal',active:true});
wire.onopen();
assert.equal(sent.at(-1).windowId, 42);
const id = sent.at(-1).menus[0].children[0].id;
function activate(action=id, windowId=42) { wire.onmessage({data:JSON.stringify({type:'activate',windowId,id:action})}); }
activate(); assert.deepEqual(executed, [[42,'NEW','']]);
activate(id, 43); activate('["UNKNOWN",""]'); activate('["CHILD",""]');
assert.equal(executed.length,1);
enabled=false; activate(); assert.equal(executed.length,1);
enabled=true; visible=false; activate(); assert.equal(executed.length,1);
visible=true; tick();
const count=sent.length; tick(); assert.equal(sent.length,count,'unchanged snapshots are not resent');
removed(42); assert.equal(sent.at(-1).menus.length,0);
activate(); assert.equal(executed.length,1);
console.log('PASS: window targeting, current enabled/visible state, disabled parent, unknown commands, disconnect state');
