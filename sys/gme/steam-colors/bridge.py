"""Push KDE palette notifications into Steam's existing loopback CEF endpoint.

No file watcher or palette polling. Browser target events cover new Steam
windows and navigation; reconnect attempts cover Steam starting/restarting.
Only CSS changes: no navigation, focus, input, reload, or Steam settings calls.
"""
import argparse
import asyncio
import configparser
import contextlib
import json
import logging
import os
from pathlib import Path
import re
import signal
from urllib.parse import urlsplit

import aiohttp
from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus

LOG = logging.getLogger('steam-system-colors')
ROLES = {
    'window': ('Window', 'BackgroundNormal'),
    'window-text': ('Window', 'ForegroundNormal'),
    'base': ('View', 'BackgroundNormal'),
    'text': ('View', 'ForegroundNormal'),
    'secondary': ('View', 'ForegroundInactive'),
    'button': ('Button', 'BackgroundNormal'),
    'button-text': ('Button', 'ForegroundNormal'),
    'highlight': ('Selection', 'BackgroundNormal'),
    'highlight-text': ('Selection', 'ForegroundNormal'),
    'link': ('View', 'ForegroundLink'),
    'error': ('View', 'ForegroundNegative'),
}
MODULES = {
    'gamepadui': {'BasicUiRoot'}, 'gamepadlibrary': {'GamepadLibrary'},
    'gamepadtabbedpage': {'GamepadTabbedPage'}, 'gamepadpage': {'GamepadPageDialogContent'},
    'gamepadhome': {'RecentSection', 'TabbedContent'}, 'mainmenu': {'mainMenuCloseDurationMS'},
    'quickaccessmenu': {'QuickAccessMenu', 'PanelSectionTitle'},
    'gamepadpagedsettings': {'PagedSettingsDialog', 'PagedSettingsDialog_PageListColumn'},
    'pagedsettings': {'PagedSettingsDialog', 'PagedSettingsDialog_PageListColumn'},
    'appdetails': {'AppDetailsOverviewPanel'}, 'libraryhome': {'LibraryHome'},
    'gamelistbar': {'GameListHomeAndSearch'}, 'steamdesktop': {'RootMenuBar', 'SuperNavBar'},
    'controls': {'FieldLabel', 'FieldDescription'},
}


def resolve_theme(theme, steam_ui):
    # Steam exports its CSS classes as plain objects. Read them as data, never
    # execute webpack modules (some modules install global React getters).
    # Resolve afresh on browser connection so Steam updates can change hashes.
    classes = {}
    for path in steam_ui.glob('*.js'):
        for match in re.finditer(r'\bexports=\{([^{}]+)\}', path.read_text(errors='replace')):
            pairs = dict(re.findall(r'(?:^|,)([A-Za-z_]\w*):"([^"\\]+)"', match[1]))
            for module, markers in MODULES.items():
                if markers <= pairs.keys():
                    for key, value in pairs.items():
                        if re.fullmatch(r'[A-Za-z_-][\w-]*', value):
                            classes.setdefault(module + '.' + key, set()).add(value)
    def selector(match):
        names = classes.get(match[1], ())
        return ':is(' + ','.join('.' + n for n in sorted(names)) + ')' if names else ':not(*)'
    return re.sub(r'\{\{([\w.]+)\}\}', selector, theme)


def palette_css(path):
    ini = configparser.ConfigParser(interpolation=None, strict=False)
    ini.optionxform = str
    with path.open() as stream:
        ini.read_file(stream)
    values = {}
    for role, (group, key) in ROLES.items():
        raw = ini.get('Colors:' + group, key)
        # Never interpolate arbitrary config text into CSS/JavaScript.
        if not re.fullmatch(r'\d{1,3},\d{1,3},\d{1,3}', raw):
            raise ValueError('invalid KDE color ' + role)
        rgb = tuple(map(int, raw.split(',')))
        if any(c > 255 for c in rgb):
            raise ValueError('invalid KDE color ' + role)
        values[role] = '#' + ''.join(f'{c:02x}' for c in rgb)
        if role == 'base':
            values['base-rgb'] = raw
    return ':root {\n' + '\n'.join(f'--steam-system-{k}: {v};' for k, v in values.items()) + '\n}\n'


def trusted_target(info):
    if info.get('type') != 'page':
        return False
    url = urlsplit(info.get('url', ''))
    if url.scheme == 'https' and url.hostname in ('steamloopback.host', 'store.steampowered.com'):
        return True
    return url.scheme == 'about' and url.path == 'blank' and bool(re.match(
        r'^(Steam|SharedJSContext|SP$|MainMenu|QuickAccess|notificationtoasts)', info.get('title', '')))


def script(css):
    # Recheck the origin at execution, including scripts installed for the next
    # document. A Steam browser navigating off-site must not recolour that site.
    return '''(() => {
      if (!(location.protocol === 'https:' && ['steamloopback.host', 'store.steampowered.com'].includes(location.hostname))
          && location.href.split('?')[0] !== 'about:blank') return;
      const apply = () => {
        if (!document.documentElement) return;
        document.documentElement.dataset.steamSystemPalette = '';
        let style = document.getElementById('steam-system-palette');
        if (!style) { style = document.createElement('style'); style.id = 'steam-system-palette'; document.documentElement.append(style); }
        style.textContent = %s;
      };
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply, {once: true});
      apply();
    })()''' % json.dumps(css)


class Bridge:
    def __init__(self, palette, theme, endpoint, steam_ui):
        self.palette, self.theme, self.endpoint = palette, theme, endpoint
        self.steam_ui = steam_ui
        self.resolved_theme = resolve_theme(theme, steam_ui)
        self.css = ''
        self.queue = asyncio.Queue()
        self.pending = {}
        self.pages = {}
        self.serial = 0
        self.ws = None
        self.debounce = None
        self.refresh()

    def refresh(self):
        try:
            css = palette_css(self.palette) + self.resolved_theme
        except (OSError, ValueError, configparser.Error) as error:
            LOG.warning('Keeping previous palette: %s', error)
            return
        if css != self.css:
            self.css = css
            self.queue.put_nowait(('palette', None))

    def notification(self, message):
        if (message.message_type == MessageType.SIGNAL
                and message.path == '/KGlobalSettings'
                and message.interface == 'org.kde.KGlobalSettings'
                and message.member == 'notifyChange'
                and message.body and message.body[0] in (0, 2)):
            if self.debounce:
                self.debounce.cancel()
            self.debounce = asyncio.get_running_loop().call_later(0.05, self.refresh)

    async def command(self, method, params=None, session=None):
        self.serial += 1
        ident = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        request = {'id': ident, 'method': method, 'params': params or {}}
        if session:
            request['sessionId'] = session
        try:
            await self.ws.send_json(request)
            return await asyncio.wait_for(future, 5)
        finally:
            self.pending.pop(ident, None)

    async def reader(self):
        try:
            async for packet in self.ws:
                if packet.type != aiohttp.WSMsgType.TEXT:
                    continue
                message = packet.json()
                if 'id' in message:
                    future = self.pending.get(message['id'])
                    if future and not future.done():
                        if 'error' in message:
                            future.set_exception(RuntimeError(str(message['error'])))
                        else:
                            future.set_result(message.get('result', {}))
                elif message.get('method') in ('Target.targetCreated', 'Target.targetInfoChanged'):
                    self.queue.put_nowait(('target', message['params']['targetInfo']))
                elif message.get('method') == 'Target.targetDestroyed':
                    self.pages.pop(message['params']['targetId'], None)
                elif message.get('method') == 'Target.detachedFromTarget':
                    session = message['params']['sessionId']
                    self.pages = {k: v for k, v in self.pages.items() if v['session'] != session}
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(ConnectionError('Steam disconnected'))
            self.queue.put_nowait(('disconnected', None))

    async def update(self, page):
        if not self.css or page.get('css') == self.css:
            return
        css = self.css
        session = page['session']
        source = script(css)
        new = await self.command('Page.addScriptToEvaluateOnNewDocument', {'source': source}, session)
        if page.get('script'):
            await self.command('Page.removeScriptToEvaluateOnNewDocument', {'identifier': page['script']}, session)
        page['script'] = new['identifier']
        result = await self.command('Runtime.evaluate', {'expression': source}, session)
        if 'exceptionDetails' in result:
            raise RuntimeError('Palette injection failed')
        # A newer notification may arrive during the RPCs. Record only what
        # actually landed, so the queued update still applies the newer CSS.
        page['css'] = css

    async def target(self, info):
        ident = info['targetId']
        if not trusted_target(info):
            page = self.pages.pop(ident, None)
            if page:
                if page.get('script'):
                    await self.command('Page.removeScriptToEvaluateOnNewDocument', {'identifier': page['script']}, page['session'])
                await self.command('Target.detachFromTarget', {'sessionId': page['session']})
            return
        if ident not in self.pages:
            attached = await self.command('Target.attachToTarget', {'targetId': ident, 'flatten': True})
            self.pages[ident] = {'session': attached['sessionId']}
        await self.update(self.pages[ident])

    async def connected(self, web):
        async with web.get(self.endpoint + '/json/version') as response:
            response.raise_for_status()
            url = (await response.json())['webSocketDebuggerUrl']
        parsed = urlsplit(url)
        if parsed.scheme != 'ws' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Steam returned a non-loopback debugger')
        async with web.ws_connect(url, heartbeat=20) as self.ws:
            self.resolved_theme = resolve_theme(self.theme, self.steam_ui)
            self.refresh()
            self.pages.clear()
            # Drop stale target events from the previous browser connection.
            self.queue = asyncio.Queue()
            receiver = asyncio.create_task(self.reader())
            try:
                await self.command('Target.setDiscoverTargets', {'discover': True})
                initial = await self.command('Target.getTargets')
                for info in initial['targetInfos']:
                    self.queue.put_nowait(('target', info))
                LOG.info('Connected to Steam; listening for KDE palette notifications')
                while True:
                    kind, info = await self.queue.get()
                    if kind == 'disconnected':
                        return
                    try:
                        if kind == 'target':
                            await self.target(info)
                        else:
                            for page in list(self.pages.values()):
                                await self.update(page)
                            LOG.info('Applied palette to %d Steam pages', len(self.pages))
                    except (RuntimeError, ConnectionError, asyncio.TimeoutError) as error:
                        # A page disappearing is normal; retain other pages.
                        LOG.debug('Steam page unavailable: %s', error)
            finally:
                # Stopping the Plasma service restores the existing Steam
                # theme, including when Steam survives a desktop-session exit.
                if not receiver.done():
                    for page in list(self.pages.values()):
                        with contextlib.suppress(Exception):
                            if page.get('script'):
                                await self.command('Page.removeScriptToEvaluateOnNewDocument', {'identifier': page['script']}, page['session'])
                            await self.command('Runtime.evaluate', {'expression':
                                "document.getElementById('steam-system-palette')?.remove(); delete document.documentElement.dataset.steamSystemPalette;"}, page['session'])
                receiver.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receiver

    async def run(self):
        bus = await MessageBus().connect()
        bus.add_message_handler(self.notification)
        rule = "type='signal',path='/KGlobalSettings',interface='org.kde.KGlobalSettings',member='notifyChange'"
        result = await bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus', member='AddMatch', signature='s', body=[rule]))
        if result.message_type == MessageType.ERROR:
            raise RuntimeError('Unable to subscribe to KDE palette notifications')
        self.refresh()  # cover a change between initial read and subscription
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as web:
                while True:
                    try:
                        await self.connected(web)
                    except (aiohttp.ClientError, OSError, ValueError, KeyError, RuntimeError, asyncio.TimeoutError) as error:
                        LOG.debug('Waiting for Steam: %s', error)
                    # Connection retry only. Colours are read on notification.
                    await asyncio.sleep(3)
        finally:
            bus.disconnect()
            await bus.wait_for_disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--css', type=Path, default=Path(__file__).with_name('theme.css'))
    parser.add_argument('--palette', type=Path, default=Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'kdeglobals')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8080')
    parser.add_argument('--steam-ui', type=Path, default=Path.home() / '.local/share/Steam/steamui')
    args = parser.parse_args()
    endpoint = urlsplit(args.endpoint)
    if endpoint.scheme != 'http' or endpoint.hostname not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('endpoint must be loopback HTTP')
    logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')
    async def serve():
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
        try:
            await Bridge(args.palette, args.css.read_text(), args.endpoint, args.steam_ui).run()
        except asyncio.CancelledError:
            pass
    asyncio.run(serve())


if __name__ == '__main__':
    main()
