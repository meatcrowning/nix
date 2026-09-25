"""Prepare the native renderer, then launch the live frontend."""
import os
from pathlib import Path
import shutil
import sys
import subprocess
from build import prepare


def main():
    library=prepare()
    if sys.argv[1:]==['--build-only']:
        print(library)
        return
    state=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'gforce-vis'
    engine=state/'engine';engine.mkdir(parents=True,exist_ok=True)
    legacy=Path.home()/'.local/share/gforce-vis/gpu/.G-Force'
    if not (engine/'.G-Force').exists() and legacy.is_file():
        shutil.copy2(legacy,engine/'.G-Force')
    old_dials=legacy.with_name('dials.json')
    if not (state/'dials.json').exists() and old_dials.is_file():
        shutil.copy2(old_dials,state/'dials.json')
    if os.environ.get('GF_HOST')=='top' and not os.environ.get('GF_SINK'):
        sinks=subprocess.run(['pactl','list','short','sinks'],capture_output=True,text=True)
        if any(len(row.split())>1 and row.split()[1]=='easyeffects_sink' for row in sinks.stdout.splitlines()):
            os.environ['GF_SINK']='easyeffects_sink'
    os.environ.setdefault('QT_LOGGING_RULES','*.debug=false')
    os.environ['GF_ENGINE_STATE_DIR']=str(engine)
    os.environ['GF_RENDERER_PATH']=str(library)
    os.environ['QT_QPA_PLATFORM']='wayland'
    os.execv(sys.executable,[sys.executable,str(Path(__file__).with_name('main.py')),*sys.argv[1:]])


if __name__=='__main__':
    try:main()
    except (KeyError,OSError,RuntimeError) as exc:
        print(f'gforce: {exc}',file=sys.stderr)
        if os.environ.get('GF_HOST')=='air':
            print('Fedora dependencies: python3-pyside6 gcc-c++ mesa-libGLES-devel mesa-libEGL-devel fftw-libs-single pulseaudio-utils',file=sys.stderr)
        sys.exit(1)
