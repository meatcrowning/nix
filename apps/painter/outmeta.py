"""What an output says about the job that made it.

One entry point, `params_for(path)`, so nothing outside this file has to know
which of the three ways a result carries its parameters it used:

1. **a still** — painter's `painter` tEXt chunk in the PNG (`pylib/pngmeta.py`);
2. **a clip painter saved since 2026-08-21** — the same JSON as an `mdta` tag in
   the MP4's `moov/udta/meta` (`pylib/mp4meta.py`), written on download;
3. **a clip from before that** — reconstructed from ComfyUI's OWN `prompt` graph,
   which `SaveVideo` has always written into the same metadata box.

(3) is why the gallery's inject menu works on the whole existing history rather
than only on what is generated from now on. It is a reading of the graph, not a
record painter kept, so it recovers what the graph actually holds — the prompt,
the sampling numbers, the seed, the duration and the pixel budget — and nothing
it does not.
"""

from __future__ import annotations

import json
from pathlib import Path

import mp4meta
import pngmeta

VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov"}


def params_for(path) -> dict | None:
    """The generation behind this output, or None if it kept none."""
    p = Path(str(path).replace("file://", ""))
    try:
        if p.suffix.lower() in VIDEO_SUFFIXES:
            tags = mp4meta.read_tags_path(p)
            own = tags.get("painter")
            if own:
                try:
                    return json.loads(own)
                except ValueError:
                    return None
            return params_from_graph(tags.get("prompt"))
        return pngmeta.load_params(p.read_bytes())
    except (OSError, ValueError):
        return None


def _nodes_of(graph: dict, *class_names):
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type", ""))
        for want in class_names:
            if want.endswith("*") and cls.startswith(want[:-1]) or cls == want:
                yield node.get("inputs") or {}
                break


def _lit(inputs, key, cast=None, default=None):
    """A literal input, never a [node, slot] link — a wire is not a value."""
    v = inputs.get(key)
    if isinstance(v, list) or v is None:
        return default
    if cast is None:
        return v
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def params_from_graph(raw) -> dict | None:
    """Painter-shaped parameters read out of a ComfyUI prompt graph.

    Only the fields the inject menu can put back are recovered, and each is
    taken from the node that owns it rather than from whichever node happens to
    have a key of that name — a `steps` on a scheduler is the sampling steps, a
    `resolution_steps` on an image scaler is not.
    """
    if not raw:
        return None
    try:
        graph = json.loads(raw) if isinstance(raw, (str, bytes)) else dict(raw)
    except ValueError:
        return None
    if not isinstance(graph, dict) or not graph:
        return None

    out: dict = {}
    for inputs in _nodes_of(graph, "MiniMaxH3*", "*ImageToVideo", "*TextToVideo"):
        text = _lit(inputs, "prompt")
        if isinstance(text, str) and text.strip():
            out["positive"] = text
        out["kind"] = "video"
        w, h = _lit(inputs, "width", int), _lit(inputs, "height", int)
        if w and h:
            out["width"], out["height"] = w, h
        frames = _lit(inputs, "length", int)
        if frames:
            out["frames"] = frames
        out["use_input_image"] = isinstance(inputs.get("first_frame"), list)
        out["use_last_frame"] = isinstance(inputs.get("last_frame"), list)
        break
    if "positive" not in out:
        texts = [t for inputs in _nodes_of(graph, "CLIPTextEncode")
                 if isinstance(t := _lit(inputs, "text"), str)]
        if texts:
            out["positive"] = texts[0]
            if len(texts) > 1 and texts[1].strip():
                out["negative"] = texts[1]

    for inputs in _nodes_of(graph, "BasicScheduler", "KSampler", "KSamplerAdvanced"):
        for key, cast in (("steps", int), ("denoise", float), ("cfg", float)):
            v = _lit(inputs, key, cast)
            if v is not None:
                out[key] = v
        sch = _lit(inputs, "scheduler")
        if isinstance(sch, str):
            out["scheduler"] = sch
        smp = _lit(inputs, "sampler_name")
        if isinstance(smp, str):
            out["sampler_name"] = smp
        break
    for inputs in _nodes_of(graph, "KSamplerSelect"):
        smp = _lit(inputs, "sampler_name")
        if isinstance(smp, str):
            out["sampler_name"] = smp
        break
    for inputs in _nodes_of(graph, "RandomNoise", "KSampler", "KSamplerAdvanced"):
        seed = _lit(inputs, "noise_seed", int)
        if seed is None:
            seed = _lit(inputs, "seed", int)
        if seed is not None:
            out["seed"] = seed
        break
    for inputs in _nodes_of(graph, "CreateVideo"):
        fps = _lit(inputs, "fps", float)
        if fps:
            out["fps"] = fps
        break
    for inputs in _nodes_of(graph, "ImageScaleToTotalPixels"):
        mp = _lit(inputs, "megapixels", float)
        if mp:
            out["megapixels"] = mp
        break
    for inputs in _nodes_of(graph, "UNETLoader", "CheckpointLoaderSimple"):
        name = _lit(inputs, "unet_name") or _lit(inputs, "ckpt_name")
        if isinstance(name, str):
            out["model"] = name
        break

    # Seconds are what the duration control holds; the graph counts frames.
    if out.get("frames") and out.get("fps"):
        out["duration"] = round(out["frames"] / float(out["fps"]), 1)

    return out or None
