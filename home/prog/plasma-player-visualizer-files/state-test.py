#!/usr/bin/env python3
"""Exercise spectrum publication and the panel callback without audio or a GUI."""
import json
import os
from pathlib import Path
import runpy
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine

HERE = Path(__file__).resolve().parent
producer = runpy.run_path(str(HERE / "cava-state.py"))
main_globals = producer["main"].__globals__


class Cava:
    stdout = ["0;20;150;-2;\n", "0;0;0;0;\n"]

    def terminate(self):
        pass

    def wait(self, timeout):
        return 0


with tempfile.TemporaryDirectory() as tmp:
    Path(tmp, "player-view.json").write_text(json.dumps({
        "view": "visualizer", "updated": time.time(),
    }))
    frames = {}
    write = producer["write_levels"]

    def record(target, levels):
        write(target, levels)
        state = json.loads(Path(target).read_text())
        assert abs(state["updated"] - time.time()) < 2
        frames.setdefault(Path(target).name, []).append(state["levels"])

    with patch.dict(os.environ, XDG_RUNTIME_DIR=tmp, CAVA="fake-cava",
                    PLAYER_VISUALIZER_CAVA_CONFIG=str(HERE / "cava.conf")), \
            patch.dict(main_globals, write_levels=record), \
            patch("subprocess.Popen", return_value=Cava()) as launch:
        assert producer["main"]() == 1
        assert launch.call_args.args[0] == ["fake-cava", "-p", str(HERE / "cava.conf")]
    assert frames["player-visualizer-panel.json"] == [[0, 20, 100, 0], [0, 0, 0, 0], []]
    assert frames["player-visualizer.json"] == [[], []]
    assert frames["player-visualizer-player.json"][0] == [0, 20, 100, 0]

app = QCoreApplication([])
engine = QJSEngine()
qml = (HERE / "main.qml").read_text()
callback = qml.split("onNewData: ", 1)[1].split("\n    }\n", 1)[0].strip()
setup = engine.evaluate('''
var now = 1000000;
Date.now = () => now;
var root = {levels: [], lastAudio: 0, hasAudio: false};
var disconnected = 0;
function disconnectSource(source) { disconnected++; }
''')
assert not setup.isError()
result = engine.evaluate("var callback = " + callback)
assert not result.isError(), result.toString()


def feed(levels, age=0, advance=0):
    result = engine.evaluate(f'''
now += {advance};
callback("test", {{stdout: JSON.stringify({{levels: {json.dumps(levels)}, updated: now/1000 - {age}}})}});
root.hasAudio;
''')
    assert not result.isError(), result.toString()
    return result.toBool()


assert not feed([0, 0])
assert feed([10, 0])
assert feed([0, 0], advance=100)  # Bridge brief gaps between beats.
assert not feed([0, 0], advance=1300)
assert not feed([90, 90], age=5)  # A dead producer cannot leave bars visible.
assert feed([5, 10])  # Works without Player or any MPRIS metadata.
assert not feed([], advance=1300)
assert engine.evaluate("disconnected").toInt() == 7
print("PASS spectrum routing, silence, stale data, cleanup, and repeated polling")
