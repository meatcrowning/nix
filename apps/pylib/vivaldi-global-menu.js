/* Loaded in Vivaldi's background document, before bundle.js. The guarded
 * getBrowserClasses seam supplies the real window context and menu modules.
 * Web pages cannot access this extension document or its private APIs. */
(() => {
    'use strict';
    const windows = new Map();
    let selected, socket, content, bookmarks = [], last = '', commands = new Map();
    const endpoint = 'ws://127.0.0.1:19191';
    globalThis.desktopVivaldiMenu = (context, execute, store, utils, state) => {
        if (state.type !== 'normal') return;
        windows.set(context.vivaldiWindowId, {context, execute, store, utils, state});
        if (state.active && selected !== context.vivaldiWindowId) {
            selected = context.vivaldiWindowId;
            setTimeout(publish, 0);
        }
    };
    function readContent() {
        vivaldi.menuContent.get('menubar', (_id, _role, items) => { content = items; });
    }
    function readBookmarks() {
        chrome.bookmarks.getTree(tree => { bookmarks = tree; });
    }
    readContent();
    readBookmarks();
    vivaldi.menuContent.onChanged.addListener(readContent);
    for (const name of ['onCreated', 'onRemoved', 'onChanged', 'onMoved', 'onChildrenReordered'])
        chrome.bookmarks[name]?.addListener(readBookmarks);
    function snapshot() {
        const w = windows.get(selected);
        if (!w || w.context.closed || !content) return null;
        const {context, execute, store, utils, state} = w;
        const id = context.vivaldiWindowId, actions = new Map();
        const shortcuts = utils.getShortcutSettings();
        const add = (key, fn) => { actions.set(key, fn); return key; };
        function bookmarkItems(nodes, depth = 0) {
            if (depth > 20) return [];
            return nodes.filter(n => !n.trash).map(n => {
                if (!n.url) return {label:n.title || 'Bookmarks', children:bookmarkItems(n.children || [], depth + 1)};
                const key = JSON.stringify(['bookmark', n.id, n.url]);
                return {label:n.title || n.url, id:add(key, () => chrome.tabs.create({windowId:id, url:n.url}))};
            });
        }
        function convert(items, parentEnabled = true) {
            return items.flatMap(item => {
                if (item.isVisible && !item.isVisible(id)) return [];
                if (utils.isSeparator(item)) return [{separator:true}];
                if (item.container) {
                    if (item.container.content !== 'CONTAINER_BOOKMARK') return [];
                    const rootId = item.container.details?.id;
                    const find = nodes => nodes.flatMap(n => n.id === rootId ? [n] : find(n.children || []));
                    return bookmarkItems(find(bookmarks)[0]?.children || []);
                }
                const enabled = parentEnabled && (!item.isEnabled || item.isEnabled(id));
                const result = {label:utils.getDisplayName(item), enabled,
                    checked:!!item.checked && !item.statestrings,
                    checkable:item.type === 'checkbox' || item.type === 'radio',
                    shortcut:utils.getShortcut(item, shortcuts).value || ''};
                if (item.items) result.children = convert(item.items, enabled);
                else if (item.commandName) {
                    const key = JSON.stringify([item.commandName, item.parameter || '']);
                    result.id = key;
                    if (enabled) add(key, () => execute(id, item.commandName, item.parameter || ''));
                } else result.enabled = false;
                return [result];
            });
        }
        // No updateCallbacks: transient snapshots must not register persistent
        // preference listeners or replace the browser's hamburger menu store.
        const menus = convert(store.makeMenuWithContent(id, content,
            {expandContainers:true, duringConfig:false, updateCallbacks:false}));
        commands = actions;
        return {type:'menus', windowId:id, title:context.document.title,
            active:!!state.active, menus};
    }
    function publish() {
        if (socket?.readyState !== WebSocket.OPEN) return;
        try {
            const value = snapshot();
            const data = JSON.stringify(value || {type:'menus', menus:[]});
            if (data !== last) { socket.send(data); last = data; }
        } catch (error) { console.warn('Desktop menu snapshot:', error); }
    }
    function connect() {
        socket = new WebSocket(endpoint);
        socket.onopen = () => { last = ''; publish(); };
        socket.onmessage = event => {
            try {
                const message = JSON.parse(event.data);
                if (message.type !== 'activate' || message.windowId !== selected) return;
                // Re-evaluate visibility and enabled state before dispatch. Only
                // identifiers present in the current menu are ever executable.
                if (!snapshot()) return;
                commands.get(message.id)?.();
                publish();
            } catch (error) { console.warn('Desktop menu action:', error); }
        };
        socket.onclose = () => { last = ''; setTimeout(connect, 5000); };
        socket.onerror = () => socket.close();
    }
    chrome.windows.onRemoved.addListener(id => {
        windows.delete(id);
        if (selected === id) { selected = undefined; commands.clear(); publish(); }
    });
    connect();
    setInterval(publish, 750);
})();
