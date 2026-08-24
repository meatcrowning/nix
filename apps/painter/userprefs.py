"""What HE set in painter, as the defaults anything else generating should use.

painter remembers a whole settings block per model — steps, cfg, sampler,
scheduler, the negative prompt, the resolution, the video duration, the toggles
— under `genByModel` in `~/.local/state/painter/prefs.json`, and restores it
when that model is selected again. Those are HIS numbers, chosen at the window,
and a generation started anywhere else should land on the same picture as
pressing generate would have.

So this reads that file and hands back the params dict `registry.build` takes.
Two rules make it safe to apply under a caller's own arguments:

* **It mirrors what painter itself would SEND**, mode by mode
  (`qml/Root.qml`'s `submit()`), rather than dumping the whole saved block: an
  edit takes only the prompt, the scale and the seed because the family's edit
  block supplies the rest, and a video job has no CFG at all. Sending the image
  fields into either would claim settings that graph never reads.
* **The positive prompt is never carried over.** It is the last thing he typed
  into the window, not a default.

Missing, unreadable or malformed prefs are simply no defaults — never an error.
The window is the owner of this file; nothing here writes to it.
"""

from __future__ import annotations

import json
import os

STATE = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "painter")
PREFS = os.path.join(STATE, "prefs.json")


def load(path=None):
    """The whole prefs document, or {} if there is not one to read."""
    try:
        with open(path or PREFS, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _sub(doc, key):
    """One of painter's JSON-in-a-string values (QML stores them stringified)."""
    raw = doc.get(key)
    if isinstance(raw, dict):
        return raw
    try:
        got = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return got if isinstance(got, dict) else {}


def saved_for(model_name, doc=None):
    """The settings block he last left this model on, or {}."""
    doc = load() if doc is None else doc
    return _sub(doc, "genByModel").get(model_name) or {}


def _num(g, key, cast=float, default=None):
    try:
        v = g[key]
    except KeyError:
        return default
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def seed_for(g, doc=None):
    """The seed his settings imply, by painter's own rule (`_start_jobs`).

    `randomSeed` beats everything (a fresh picture every press is what it means),
    `reuseSeed` re-runs the last batch's base seed, and otherwise it is the seed
    sitting in the box. `None` means "he expressed no preference"."""
    if not g:
        return None
    if bool(g.get("randomSeed")):
        import secrets
        return secrets.randbelow(2 ** 53)
    if bool(g.get("reuseSeed")):
        last = _num(load() if doc is None else doc, "lastSeed", float, -1.0)
        if last is not None and last >= 0:
            return int(last)
    seed = _num(g, "seed", float)
    return int(seed) if seed is not None and seed >= 0 else None


def params_for(model_name, kind="image", doc=None):
    """His saved settings for one model, as build() params for `kind`.

    `kind` is "image", "edit" or "video" — the three shapes painter's own
    `submit()` sends, and for the same reasons. The seed is left out: it is a
    policy rather than a value (see `seed_for`), and a caller that pins a seed
    must not have a random one laid under it.
    """
    doc = load() if doc is None else doc
    g = saved_for(model_name, doc)
    if not g:
        return {}
    out = {}

    def put(key, src=None, cast=float):
        v = _num(g, src or key, cast)
        if v is not None:
            out[key] = v

    if kind == "edit":
        # The family's edit block supplies steps, cfg and shift; the controls
        # for them are not even on screen in this mode.
        if "editNoScale" in g:
            out["editNoScale"] = bool(g["editNoScale"])
        put("editMegapixels")
        return out

    put("steps", cast=int)
    put("denoise")
    for key in ("sampler_name", "scheduler"):
        if isinstance(g.get(key), str) and g[key]:
            out[key] = g[key]

    if kind == "video":
        put("duration")
        put("fps")
        put("megapixels")
        put("width", cast=int)
        put("height", cast=int)
        return out

    put("cfg")
    put("batch_size", cast=int)
    put("width", cast=int)
    put("height", cast=int)
    if isinstance(g.get("negative"), str) and g["negative"].strip():
        out["negative"] = g["negative"]
    out["toggles"] = {"negpip": bool(g.get("negpip")),
                      "model_sampling": bool(g.get("modelSampling"))}
    ms = g.get("ms")
    if isinstance(ms, dict) and ms:
        out["model_sampling"] = dict(ms)
    return out


def loras_for(reg, entry, doc=None):
    """His LoRA stack, filtered to what applies to this model.

    painter keeps one stack (`loras`), not one per model, and drops on restore
    any name that is not among the LoRAs applicable to the selected model — so
    the same filter is what makes carrying it over safe."""
    doc = load() if doc is None else doc
    try:
        rows = json.loads(doc.get("loras") or "[]")
    except (ValueError, TypeError):
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("enabled", True):
            continue
        found = reg.find(str(r.get("name") or ""))
        if found is None or not reg.lora_compat(found, entry)["ok"]:
            continue
        out.append({"name": found.name,
                    "strength": float(r.get("strength", 1.0) or 1.0),
                    "patches_clip": found.patches_clip})
    return out
