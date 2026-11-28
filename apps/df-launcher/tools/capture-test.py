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
