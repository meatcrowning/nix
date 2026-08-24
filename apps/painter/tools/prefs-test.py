#!/usr/bin/env python3
"""His painter settings, as the defaults everything else generates with.

Pure — a fabricated prefs document, no backend, no window, no weights. What is
pinned here is the SHAPE per mode: an edit takes only the scale keys, a video
takes no CFG, an image carries his negative prompt and his toggles, and the
positive prompt is never carried over at all.

    python3 tools/prefs-test.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

_TMP = Path(tempfile.mkdtemp(prefix="painter-prefs-"))
os.environ["XDG_STATE_HOME"] = str(_TMP)
(_TMP / "painter").mkdir(parents=True)

import userprefs as UP  # noqa: E402

FAILED = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label
          + (("  — " + detail) if detail and not cond else ""))
    if not cond:
        FAILED.append(label)


GEN = {
    "positive": "the last thing he typed",
    "negative": "smooth vector linework, gradient shading",
    "steps": 50, "cfg": 0.7, "denoise": 1, "sampler_name": "euler_cfg_pp",
    "scheduler": "beta", "seed": 426108493918706, "randomSeed": False,
    "reuseSeed": False, "batch_size": 1, "count": 1,
    "aspectW": 2, "aspectH": 3, "megapixels": 2, "multiple": 64,
    "width": 1152, "height": 1728, "duration": 6, "fps": 24,
    "editNoScale": True, "editMegapixels": 1.5,
    "negpip": True, "modelSampling": True,
    "ms": {"shift_start": 3.5, "shift_end": 1.2},
}
DOC = {"genByModel": json.dumps({"anima-base-v1.0.safetensors": GEN}),
       "lastSeed": 277973941839831.0,
       "loras": json.dumps([{"name": "gone.safetensors", "strength": 0.8,
                             "enabled": True}])}
(_TMP / "painter" / "prefs.json").write_text(json.dumps(DOC), encoding="utf-8")

M = "anima-base-v1.0.safetensors"

print("\nan image job")
p = UP.params_for(M, "image")
check("his resolution comes across", p.get("width") == 1152 and p.get("height") == 1728, str(p))
check("...and his sampling", p.get("steps") == 50 and p.get("cfg") == 0.7
      and p.get("sampler_name") == "euler_cfg_pp" and p.get("scheduler") == "beta", str(p))
check("...and his negative prompt", "gradient shading" in (p.get("negative") or ""), str(p))
check("...and his toggles", p.get("toggles") == {"negpip": True, "model_sampling": True}, str(p))
check("...and the shift block", (p.get("model_sampling") or {}).get("shift_start") == 3.5, str(p))
check("the POSITIVE prompt is never carried over", "positive" not in p, str(p))

print("\na video job")
p = UP.params_for(M, "video")
check("length and fps come across", p.get("duration") == 6 and p.get("fps") == 24, str(p))
check("a video job carries no CFG", "cfg" not in p, str(p))
check("...and no toggles", "toggles" not in p, str(p))

print("\nan edit")
p = UP.params_for(M, "edit")
check("an edit takes only the scale keys",
      set(p) == {"editNoScale", "editMegapixels"}, str(p))
check("...at his values", p.get("editNoScale") is True
      and p.get("editMegapixels") == 1.5, str(p))

print("\nthe seed is a policy, not a value")
check("the seed is never in the params", "seed" not in UP.params_for(M, "image"))
check("a fixed seed is his seed", UP.seed_for(GEN) == 426108493918706)
check("randomSeed is a fresh one every time",
      len({UP.seed_for({**GEN, "randomSeed": True}) for _ in range(4)}) > 1)
check("reuseSeed re-runs the last batch's",
      UP.seed_for({**GEN, "reuseSeed": True}) == 277973941839831)
check("no settings, no opinion", UP.seed_for({}) is None)

print("\nnothing to read is no defaults, never an error")
os.environ["XDG_STATE_HOME"] = str(_TMP / "nowhere")
UP.PREFS = os.path.join(str(_TMP / "nowhere"), "painter", "prefs.json")
check("a missing prefs file", UP.params_for(M, "image") == {})
bad = _TMP / "bad.json"
bad.write_text("{ not json", encoding="utf-8")
check("a corrupt one", UP.load(str(bad)) == {})
check("a model he has never selected",
      UP.params_for("nope.safetensors", "image", doc=DOC) == {})

print()
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
print("all good")
