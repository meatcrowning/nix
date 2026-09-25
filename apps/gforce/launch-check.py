"""Check migration and build-only behavior without launching Qt or audio."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import launch

class Launched(Exception):pass
with tempfile.TemporaryDirectory(prefix='gforce-launch-') as tmp:
    root=Path(tmp);home=root/'home';config=root/'config'
    legacy=home/'.local/share/gforce-vis/gpu';legacy.mkdir(parents=True)
    (legacy/'.G-Force').write_text('legacy engine preferences')
    (legacy/'dials.json').write_text('{"grid":2048}')
    calls=[]
    def capture(*args):calls.append(args);raise Launched
    with patch.object(launch,'prepare',return_value=root/'renderer.so'), \
         patch.object(Path,'home',return_value=home), \
         patch.dict(os.environ,{'XDG_CONFIG_HOME':str(config),'GF_HOST':'air'}), \
         patch.object(launch.os,'execv',side_effect=capture), \
         patch.object(launch.subprocess,'run',side_effect=AssertionError('must not query audio on air')):
        with patch.object(launch.sys,'argv',['launch.py','--build-only']),contextlib.redirect_stdout(io.StringIO()) as out:
            launch.main()
        assert not config.exists() and not calls
        assert out.getvalue().strip()==str(root/'renderer.so')
        with patch.object(launch.sys,'argv',['launch.py']):
            try:launch.main()
            except Launched:pass
        state=config/'gforce-vis'
        assert (state/'engine/.G-Force').read_text()=='legacy engine preferences'
        assert (state/'dials.json').read_text()=='{"grid":2048}'
        assert calls[-1][1][1].endswith('/main.py')
        assert os.environ['GF_RENDERER_PATH']==str(root/'renderer.so')
        (state/'dials.json').write_text('{"grid":1024}')
        (state/'engine/.G-Force').write_text('current preferences')
        with patch.object(launch.sys,'argv',['launch.py']):
            try:launch.main()
            except Launched:pass
        assert (state/'dials.json').read_text()=='{"grid":1024}'
        assert (state/'engine/.G-Force').read_text()=='current preferences'
print('PASS: build-only has no launch/state side effects; migration preserves existing settings')
