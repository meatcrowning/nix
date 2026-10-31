#!/usr/bin/env python3
"""Exercise activation migration without touching the real user's defaults."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HELPER = Path(__file__).resolve().parents[1] / 'home/prog/mime-files/set-defaults.py'
with tempfile.TemporaryDirectory(prefix='mime-defaults-test-') as tmp:
    root = Path(tmp)
    cfg = root / 'config'
    cfg.mkdir()
    env = dict(os.environ, XDG_CONFIG_HOME=str(cfg), XDG_STATE_HOME=str(root / 'state'))

    def run(*args):
        subprocess.run([sys.executable, str(HELPER), *args], env=env, check=True)

    generic = cfg / 'mimeapps.list'
    generic.write_text('# keep\n[Default Applications]\nvideo/mp4=mpv.desktop;\n'
                       'text/plain=editor.desktop;\n[Added Associations]\ntext/plain=editor.desktop;\n')
    args = ('--remove-matching', '--once', 'migration',
            'video/mp4=viewer.desktop', 'text/plain=editor.desktop')
    run(*args)
    assert generic.read_text() == ('# keep\n[Default Applications]\nvideo/mp4=mpv.desktop;\n'
                                   '[Added Associations]\ntext/plain=editor.desktop;\n')
    run('text/plain=editor.desktop')  # A user explicitly chooses the old default again.
    before = generic.read_bytes()
    run(*args)
    assert generic.read_bytes() == before

    kde = cfg / 'kde-mimeapps.list'
    kde.write_text('[Default Applications]\nvideo/mp4=org.kde.haruna.desktop\n'
                   'text/plain=custom.desktop;\n')
    run('--file', kde.name, '--remove-matching', '--once', 'migration',
        'video/mp4=org.kde.haruna.desktop', 'text/plain=org.kde.kate.desktop')
    assert kde.read_text() == '[Default Applications]\ntext/plain=custom.desktop;\n'

    browser = cfg / 'kdeglobals'
    browser.write_text('[General]\nBrowserApplication=chosen.desktop\n')
    run('--file', browser.name, '--section', 'General', '--only-missing',
        'BrowserApplication=surfer.desktop')
    assert browser.read_text() == '[General]\nBrowserApplication=chosen.desktop\n'
    run('--file', browser.name, '--section', 'General', '--only-missing', 'Other=seed')
    assert 'Other=seed\n' in browser.read_text()

    # Missing files/sections must not gain obsolete defaults during migration.
    run('--file', 'absent.list', '--remove-matching', '--once', 'migration', 'video/mp4=old.desktop')
    assert not (cfg / 'absent.list').exists()
    generic.write_text('[Added Associations]\nvideo/mp4=mpv.desktop;\n')
    run('--remove-matching', '--once', 'second', 'video/mp4=mpv.desktop')
    assert generic.read_text() == '[Added Associations]\nvideo/mp4=mpv.desktop;\n'
print('mime default migration and user-choice persistence: OK')
