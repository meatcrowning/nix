"""Optional rendering check: isolated headless browser, private bus, temporary profile.
Set STEAM_COLOR_TEST_BROWSER to a Chromium executable; use tools/lib/session-guard.sh
offscreen guard and dbus-run-session with no service activation directories.
"""
import logging
import signal
import asyncio, contextlib, json, os, pathlib, subprocess, sys, tempfile
import aiohttp
from dbus_next import Message
from dbus_next.aio import MessageBus
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from bridge import Bridge
from test_bridge import palette

async def main():
    assert os.environ['QT_QPA_PLATFORM']=='offscreen'
    assert os.environ['STEAM_COLOR_TEST_PRIVATE_BUS']=='1'
    assert not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY')
    with tempfile.TemporaryDirectory(prefix='steam-colors-render-') as directory:
        root=pathlib.Path(directory)
        profile=root/'profile'; profile.mkdir()
        runtime=root/'runtime'; runtime.mkdir(mode=0o700)
        env=dict(os.environ,XDG_CONFIG_HOME=str(root/'config'),XDG_CACHE_HOME=str(root/'cache'),PULSE_SERVER='unix:/nonexistent',XDG_RUNTIME_DIR=str(runtime))
        proc=subprocess.Popen([os.environ['STEAM_COLOR_TEST_BROWSER'],'--headless=new','--ozone-platform=headless','--disable-gpu','--password-store=basic','--disable-dev-shm-usage','--disable-background-networking','--disable-extensions','--disable-sync','--mute-audio','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',f'--user-data-dir={profile}','about:blank'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        task=None; bus=None
        try:
            async with asyncio.timeout(20):
                while not (profile/'DevToolsActivePort').exists():
                    assert proc.poll() is None, 'isolated browser exited'
                    await asyncio.sleep(.05)
            port=int((profile/'DevToolsActivePort').read_text().splitlines()[0]); assert port!=8080
            async with aiohttp.ClientSession() as web:
                pages=await (await web.get(f'http://127.0.0.1:{port}/json/list')).json()
                async with web.ws_connect(next(p for p in pages if p['url']=='about:blank' and p['type']=='page')['webSocketDebuggerUrl']) as ws:
                    serial=0
                    async def evaluate(expression):
                        nonlocal serial
                        serial+=1
                        await ws.send_json({'id':serial,'method':'Runtime.evaluate','params':{'expression':expression,'returnByValue':True}})
                        async for m in ws:
                            d=m.json()
                            if d.get('id')==serial:
                                assert 'exceptionDetails' not in d['result'], d
                                return d['result']['result'].get('value')
                    await evaluate('document.title="Steam Big Picture Mode"; document.body.innerHTML='+json.dumps('<style>.home-library-grid {background:#000 !important;color:#fff}.hlg-sort-button{background:#111;color:white}.nativeWindow{background:black!important}</style><div class="nativeWindow">Window</div><div class="home-library-grid"><span class="hlg-metadata">Developer</span><button class="hlg-sort-button">Sort</button></div>'))
                    (root/'ui.js').write_text('a.exports={BasicUiRoot:"nativeWindow"};')
                    config=root/'kdeglobals';palette(config,'220,230,240')
                    config.write_text(config.read_text().replace('ForegroundNormal=220,230,240','ForegroundNormal=10,20,30').replace('[Colors:Window]\nBackgroundNormal=220,230,240','[Colors:Window]\nBackgroundNormal=30,40,50'))
                    bridge=Bridge(config,pathlib.Path(__file__).with_name('theme.css').read_text(),f'http://127.0.0.1:{port}',root)
                    task=asyncio.create_task(bridge.run());bus=await MessageBus().connect()
                    async with asyncio.timeout(5):
                        while not await evaluate('!!document.getElementById("steam-system-palette")'):await asyncio.sleep(.02)
                    result=await evaluate('Object.fromEntries([".nativeWindow",".home-library-grid",".hlg-sort-button"].map(s=>{const c=getComputedStyle(document.querySelector(s));return [s,[c.backgroundColor,c.color]]}))')
                    assert result['.home-library-grid']==['rgb(220, 230, 240)','rgb(10, 20, 30)'],result
                    assert result['.nativeWindow'][0]=='rgb(30, 40, 50)',result
                    palette(config,'90,100,110')
                    await bus.send(Message.new_signal('/KGlobalSettings','org.kde.KGlobalSettings','notifyChange','ii',[0,0]))
                    async with asyncio.timeout(5):
                        while await evaluate('getComputedStyle(document.querySelector(".home-library-grid")).backgroundColor')!='rgb(90, 100, 110)':await asyncio.sleep(.02)
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError): await task
                    task=None
                    assert not await evaluate('!!document.getElementById("steam-system-palette")')
                    assert await evaluate('getComputedStyle(document.querySelector(".home-library-grid")).backgroundColor')=='rgb(0, 0, 0)'
                    print('PASS: real headless browser applies native roles, overrides OLED CSS, and updates on KDE signal')
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await task
            if bus:
                bus.disconnect();await bus.wait_for_disconnect()
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            await asyncio.sleep(.2)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
