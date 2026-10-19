#!/usr/bin/env python3
"""Bounded fake inference: stream framing, cutoff, timeout and async worker."""
import os
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tagger_worker import Tags, Prompt, generate

p = Tags(3)
assert not p.feed('red fox, RED FOX, , snow')
assert not p.feed('y pine, winter')
assert p.feed(' [end of text]')
assert p.items == ['red fox', 'snowy pine', 'winter']
p = Tags(1)
assert not p.feed('unfinished')
assert p.feed(',extra,') and p.items == ['unfinished']

p = Prompt()
assert not p.feed('A red fox rests in snow. Its tail is par')
assert p.finish() == 'A red fox rests in snow.'
p = Prompt()
p.feed('A red fox rests [end of text]')
assert p.finish() == 'A red fox rests'
p = Prompt()
p.feed('Incomplete sentence')
try:
    p.finish()
except ValueError:
    pass
else:
    raise AssertionError('accepted truncated prose without a complete sentence')

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    binary, model = root / 'fake-llama', root / 'model'
    model.touch()
    def fake(body):
        binary.write_text('#!' + sys.executable + '\nimport os, time\n' + body)
        binary.chmod(0o700)
    fake("print('fox, snow, extra, more,', flush=True)\ntime.sleep(20)\n")
    start = time.monotonic()
    assert generate(dict(count=2, caption='fox in snow'), str(binary), str(model)) == ['fox', 'snow']
    assert time.monotonic() - start < 3, 'did not stop inference at the requested count'
    fake("print('fox, incomple', flush=True)\n")
    try:
        generate(dict(count=2, caption='fox in snow'), str(binary), str(model))
    except ValueError as e:
        assert 'only 1 of 2' in str(e)
    else:
        raise AssertionError('accepted a truncated tag')
    fake("import sys\nassert sys.argv[sys.argv.index('-n') + 1] == '48'\nprint('A fox rests in snow. An unfinished tail', flush=True)\n")
    assert generate(dict(task='prompt', tokens=48, caption='fox'), str(binary), str(model)) == 'A fox rests in snow.'
    fake("import sys\nprompt = sys.argv[sys.argv.index('-p') + 1]\nassert 'MOSS accepts' in prompt and 'negative image prompt' in prompt\nprint('blurred eyes, duplicated limbs, partial', flush=True)\n")
    assert generate(dict(task='prompt', scope='negative', tokens=48, caption='', scene='A fox.', moss=True), str(binary), str(model)) == 'blurred eyes, duplicated limbs'
    fake("import sys\nprompt = sys.argv[sys.argv.index('-p') + 1]\nassert 'cohesive visual description' in prompt and 'one region' not in prompt\nprint('A fox rests in snow.[end of text]', flush=True)\n")
    assert generate(dict(task='prompt', scope='positive', tokens=48, caption='fox'), str(binary), str(model)) == 'A fox rests in snow.'
    fake('time.sleep(20)\n')
    start = time.monotonic()
    try:
        generate(dict(count=2, caption='fox'), str(binary), str(model), timeout=.1)
    except ValueError as e:
        assert 'timed out' in str(e)
    else:
        raise AssertionError('missing inference deadline')
    assert time.monotonic() - start < 3
    assert os.environ.get('QT_QPA_PLATFORM') == 'offscreen'
    from PySide6.QtCore import QCoreApplication, QTimer
    from tagger import Tagger
    app = QCoreApplication([])
    os.environ.update(PAINTER_TAG_LLAMA=str(binary), PAINTER_TAG_MODEL=str(model), XDG_RUNTIME_DIR=tmp)
    fake("print('fox, snow,', flush=True)\ntime.sleep(20)\n")
    service = Tagger()
    replies = []
    def finished(reply):
        replies.append(reply)
        app.quit()
    assert service.start(dict(count=2, caption='fox in snow'), finished)['busy']
    assert service.start(dict(count=2, caption='another'))['error']
    QTimer.singleShot(5000, app.quit)
    app.exec()
    service.cancel()
    assert replies and replies[0]['tags'] == ['fox', 'snow'], replies
    assert not service.result['busy'] and service.process is None
print('PASS: complete unique tags, exact cutoff, truncated output, deadline and async process cleanup')
