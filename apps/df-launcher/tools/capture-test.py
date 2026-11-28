"""Run with a compiled capture helper as argv[1]; uses scratch files only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

binary = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix="df-ambience-capture-") as temporary:
    root = Path(temporary)
    home = root / "home"
    library = home / ".local/share/df-launcher/ambience.so"
    library.parent.mkdir(parents=True)
    source = root / "empty.c"
    source.write_text("int placeholder;\n")
    subprocess.run(["gcc", "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
    child = root / "child.py"
    child.write_text("import os,json; print(json.dumps(dict(os.environ)))\n")
    for label in ("enabled", "disabled", "blocked", "missing"):
        work = root / label
        work.mkdir()
        (work / "dfhack-config").mkdir()
        run = work / "run"
        run.mkdir()
        environment = dict(os.environ, HOME=str(home), LD_PRELOAD=str(library))
        environment.pop("DF_AMBIENCE_FIX", None)
        environment.pop("DF_AMBIENCE_STATE", None)
        if label == "disabled":
            environment["DF_AMBIENCE_FIX"] = "0"
        if label == "blocked":
            (work / "dfhack-config/scripts").write_text("not a directory")
        if label == "missing":
            library.rename(library.with_suffix(".disabled"))
            environment.pop("LD_PRELOAD")
        result = subprocess.run(
            [str(binary), "--capture-game", str(run), sys.executable, str(child)],
            env=environment, cwd=work, text=True, capture_output=True, check=True)
        child_environment = json.loads(result.stdout)
        script = work / "dfhack-config/scripts/df-launcher-ambience.lua"
        if label == "enabled":
            assert child_environment["DF_AMBIENCE_STATE"] == str(run / "ambience-state.txt")
            assert child_environment["LD_PRELOAD"] == f"{library}:{library}"
            assert script.read_text() == (Path(__file__).parent.parent / "ambience.lua").read_text()
            assert "df-launcher-ambience" in (work / "dfhack-config/init/dfhack.df-launcher-ambience.init").read_text()
        else:
            assert "DF_AMBIENCE_STATE" not in child_environment
            assert not script.exists()
        if label == "blocked":
            assert "Activity observer unavailable:" in (run / "game.txt").read_text()
        assert "Exited with code 0" in (run / "game-result.txt").read_text()
        print(label, "passed")

    # Exercise the outer Steam entry point, including runtimes with a -- game
    # boundary and Steam launching dwarfort as the command itself.
    library.with_suffix(".disabled").rename(library)
    game = root / "dwarfort"
    game.write_text(f"#!{sys.executable}\nimport os,json,sys\nprint(json.dumps({{'env':dict(os.environ),'args':sys.argv[1:]}}))\n")
    game.chmod(0o755)
    runtime = root / "runtime"
    runtime.write_text('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n')
    runtime.chmod(0o755)
    for label, command in (("direct-game", [str(game)]),
                           ("steam-runtime", [str(runtime), "--runtime-option", "--", str(game)])):
        work = root / label
        work.mkdir()
        (work / "dfhack-config").mkdir()
        environment = dict(os.environ, HOME=str(home))
        for key in ("LD_PRELOAD", "DF_AMBIENCE_FIX", "DF_AMBIENCE_STATE"):
            environment.pop(key, None)
        subprocess.run([str(binary), *command, "argument with spaces"], cwd=work,
                       env=environment, capture_output=True, check=True)
        runs = sorted((home / ".local/state/df-launcher/runs").iterdir())
        run = runs[-1]
        recorded = json.loads((run / "process-stdout.txt").read_text())
        assert recorded["env"]["LD_PRELOAD"] == str(library)
        assert recorded["env"]["DF_AMBIENCE_STATE"] == str(run / "ambience-state.txt")
        assert recorded["args"] == ["argument with spaces"]
        assert "Game: Exited with code 0" in (run / "result.txt").read_text()
        print(label, "passed")
