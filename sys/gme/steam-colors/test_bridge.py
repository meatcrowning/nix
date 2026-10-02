"""Run on a private bus: dbus-run-session -- python3 -m unittest discover -s ..."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp import web
from dbus_next import Message
from dbus_next.aio import MessageBus
from bridge import Bridge, ROLES, palette_css, resolve_theme, script, trusted_target


def palette(path, color):
    groups = {}
    for group, key in ROLES.values():
        groups.setdefault(group, {})[key] = color
    path.write_text('\n'.join('[Colors:'+g+']\n'+'\n'.join(k+'='+v for k,v in keys.items()) for g,keys in groups.items()))


class ModelTests(unittest.TestCase):
    def test_palette_preserves_roles_and_rejects_invalid_css(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'kdeglobals'
            palette(path, '1,2,3')
            self.assertIn('--steam-system-base: #010203;', palette_css(path))
            path.write_text(path.read_text().replace('[Colors:Selection]\nBackgroundNormal=1,2,3', '[Colors:Selection]\nBackgroundNormal=4,5,6'))
            self.assertIn('--steam-system-highlight: #040506;', palette_css(path))
            palette(path, '256,0,0')
            with self.assertRaises(ValueError): palette_css(path)
            palette(path, 'red; background:url(https://example.com)')
            with self.assertRaises(ValueError): palette_css(path)

    def test_target_scope(self):
        self.assertTrue(trusted_target({'type':'page','url':'https://steamloopback.host/library','title':''}))
        self.assertTrue(trusted_target({'type':'page','url':'about:blank?browserviewpopup=1','title':'MainMenu_uid7'}))
        for url in ['https://steamloopback.host.evil.test/', 'https://example.com', 'file:///tmp/test', 'about:blank']:
            self.assertFalse(trusted_target({'type':'page','url':url,'title':'Unrelated'}))
        self.assertFalse(trusted_target({'type':'worker','url':'https://steamloopback.host/'}))

    def test_class_resolution_uses_css_exports_without_executing_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'ui.js').write_text('a.exports={BasicUiRoot:"_currentHash",OpaqueBackground:"newHash"};evil();')
            result = resolve_theme('{{gamepadui.BasicUiRoot}}, {{gamepadui.OpaqueBackground}}, {{missing.Class}}', root)
            self.assertEqual(result, ':is(._currentHash), :is(.newHash), :not(*)')


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Tests must never connect to the desktop's session bus or Steam port.
        if os.environ.get('STEAM_COLOR_TEST_PRIVATE_BUS') != '1':
            raise RuntimeError('run this test inside its own dbus-run-session')
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.palette = root/'kdeglobals'
        palette(self.palette, '10,20,30')
        self.messages = []
        self.sockets = []
        self.targets = [{'targetId':'home','type':'page','title':'SharedJSContext','url':'https://steamloopback.host/library'}]
        self.ident = 0
        self.ready = asyncio.Event()
        async def version(request):
            return web.json_response({'webSocketDebuggerUrl':f'ws://127.0.0.1:{self.port}/browser'})
        async def browser(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            self.sockets.append(ws)
            async for packet in ws:
                message = packet.json()
                self.messages.append(message)
                method = message['method']
                result = {}
                if method == 'Target.getTargets': result = {'targetInfos':self.targets}
                if method == 'Target.attachToTarget': result = {'sessionId':message['params']['targetId']}
                if method == 'Page.addScriptToEvaluateOnNewDocument':
                    self.ident += 1
                    result = {'identifier':str(self.ident)}
                await ws.send_json({'id':message['id'],'result':result})
                if method == 'Runtime.evaluate': self.ready.set()
            return ws
        app = web.Application()
        app.router.add_get('/json/version', version)
        app.router.add_get('/browser', browser)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner,'127.0.0.1',0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.bridge = Bridge(self.palette,'/* isolated theme */',f'http://127.0.0.1:{self.port}',root)
        self.task = asyncio.create_task(self.bridge.run())
        self.bus = await MessageBus().connect()
        await asyncio.wait_for(self.ready.wait(),3)

    async def asyncTearDown(self):
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await self.task
        self.bus.disconnect()
        await self.bus.wait_for_disconnect()
        await self.runner.cleanup()
        self.tmp.cleanup()

    def evaluations(self):
        return [m for m in self.messages if m['method']=='Runtime.evaluate']

    async def notify(self, change=0):
        await self.bus.send(Message.new_signal('/KGlobalSettings','org.kde.KGlobalSettings','notifyChange','ii',[change,0]))

    async def wait_evaluations(self, count):
        async with asyncio.timeout(3):
            while len(self.evaluations()) < count: await asyncio.sleep(.01)

    async def test_notifications_coalesce_and_no_file_polling(self):
        before = len(self.evaluations())
        palette(self.palette,'40,50,60')
        await asyncio.sleep(.15)
        self.assertEqual(len(self.evaluations()),before)
        await self.notify(1)  # fonts, not palette
        await asyncio.sleep(.1)
        self.assertEqual(len(self.evaluations()),before)
        await self.notify()
        palette(self.palette,'70,80,90')
        await self.notify(2)
        await self.wait_evaluations(before+1)
        self.assertIn('#46505a',self.evaluations()[-1]['params']['expression'])
        self.assertEqual(len(self.evaluations()),before+1)
        await self.notify()
        await asyncio.sleep(.15)
        self.assertEqual(len(self.evaluations()),before+1)

    async def test_new_windows_receive_latest_palette_and_unrelated_pages_do_not(self):
        before = len(self.evaluations())
        for title,url,ident in [('MainMenu_uid2','about:blank?browserviewpopup=1','menu'),('Browser','https://example.com','external')]:
            await self.sockets[-1].send_json({'method':'Target.targetCreated','params':{'targetInfo':{
                'targetId':ident,'type':'page','title':title,'url':url}}})
        await self.wait_evaluations(before+1)
        await asyncio.sleep(.1)
        self.assertEqual(len(self.evaluations()),before+1)
        self.assertEqual(self.evaluations()[-1]['sessionId'],'menu')
        self.assertIn('#0a141e',self.evaluations()[-1]['params']['expression'])

    async def test_invalid_palette_preserves_previous_and_recovers(self):
        before = len(self.evaluations())
        palette(self.palette,'oops')
        await self.notify()
        await asyncio.sleep(.15)
        self.assertEqual(len(self.evaluations()),before)
        palette(self.palette,'90,80,70')
        await self.notify()
        await self.wait_evaluations(before+1)
        self.assertIn('#5a5046',self.evaluations()[-1]['params']['expression'])

    async def test_reconnect_applies_palette_changed_while_steam_was_closed(self):
        before = len(self.evaluations())
        await self.sockets[-1].close()
        palette(self.palette,'100,110,120')
        await self.notify()
        async with asyncio.timeout(7):
            while len(self.evaluations()) == before: await asyncio.sleep(.01)
        self.assertIn('#646e78',self.evaluations()[-1]['params']['expression'])

    async def test_notification_during_inflight_push_does_not_lose_final_palette(self):
        other = Bridge(self.palette, '', '', Path(self.tmp.name))
        old = other.css
        expressions = []
        async def command(method, params, session):
            if method == 'Page.addScriptToEvaluateOnNewDocument':
                other.css = '/* newer palette arrived during RPC */'
                return {'identifier': '1'}
            if method == 'Runtime.evaluate': expressions.append(params['expression'])
            return {}
        other.command = command
        page = {'session': 'fake'}
        await other.update(page)
        self.assertEqual(page['css'], old)
        await other.update(page)
        self.assertEqual(page['css'], other.css)
        self.assertIn('newer palette', expressions[-1])


if __name__ == '__main__': unittest.main()
