"""What an output says about the job that made it.

One entry point, `params_for(path)`, so nothing outside this file has to know
which of the ways a result carries its parameters it used:

1. **a still** — painter's `painter` tEXt chunk in the PNG (`pylib/pngmeta.py`);
2. **a clip painter saved since 2026-08-21** — the same JSON as an `mdta` tag in
   the MP4's `moov/udta/meta` (`pylib/mp4meta.py`), written on download;
3. **anything without painter's own record** — reconstructed from ComfyUI's OWN
   `prompt` graph, which `SaveImage` and `SaveVideo` always write.

A still lacks (1) far more often than its age suggests: on top, ComfyUI saves
into the same directory the gallery reads, and painter tags a still only by
overwriting that file with the copy it downloaded. A job book submitted through
the tunnel is downloaded and tagged on BOOK, so top keeps ComfyUI's untagged
original — as do outputs queued from ComfyUI's own web UI.

(3) is why the gallery's inject menu works on the whole existing history rather
than only on what is generated from now on. It is a reading of the graph, not a
record painter kept, so it recovers what the graph actually holds — the prompt,
the sampling numbers, the seed, the duration and the pixel budget — and nothing
it does not.
"""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
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
        text = pngmeta.read_text(p.read_bytes())
        own = text.get("painter")
        if own:
            try:
                return json.loads(own)
            except ValueError:
                return None
        out = params_from_graph(text.get("prompt"))
        # A video graph that saved a PNG is the still mode of a video model.
        if out and out.get("kind") == "video":
            out["kind"] = "still"
        return out
    except (OSError, ValueError):
        return None


def _nodes_of(graph: dict, *class_names):
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type", ""))
        if any(fnmatchcase(cls, want) for want in class_names):
            yield node.get("inputs") or {}


def _first(graph: dict, *class_names):
    """The inputs of the first node of any of these classes, or {}."""
    for inputs in _nodes_of(graph, *class_names):
        return inputs
    return {}


def _cond_text(graph: dict, link, depth=0):
    """The prompt text a conditioning wire was encoded from, or None.

    Follows the wire back through whatever sits between the encoder and the
    sampler (ReferenceLatent and its kin pass `conditioning` through). An
    encoder with two outputs keeps the negative on its second slot, and a
    ConditioningZeroOut is an empty negative rather than its source's words.
    """
    if not isinstance(link, list) or len(link) < 2 or depth > 16:
        return None
    node = graph.get(str(link[0]))
    if not isinstance(node, dict):
        return None
    inputs = node.get("inputs") or {}
    if node.get("class_type") == "ConditioningZeroOut":
        return ""
    if link[1] == 1 and isinstance(inputs.get("negative_prompt"), str):
        return inputs["negative_prompt"]
    for key in ("text", "prompt"):
        if isinstance(inputs.get(key), str):
            return inputs[key]
    return _cond_text(graph, inputs.get("conditioning"), depth + 1)


def _unfold_negpip(text: str):
    """Split a NegPip-folded positive back into its two boxes, or None.

    registry.py appends the negative to the positive as one final weighted
    group, `pos, (neg:-1)`; a group ending the prompt with a negative weight is
    that fold. Escaped parentheses (`\\(`, `\\)`) are literal tag text.
    """
    t = text.rstrip()
    if not t.endswith(")") or t.endswith("\\)"):
        return None
    depth = 0
    for i in range(len(t) - 1, -1, -1):
        if i > 0 and t[i - 1] == "\\":
            continue
        if t[i] == ")":
            depth += 1
        elif t[i] == "(":
            depth -= 1
            if depth == 0:
                inner = t[i + 1:-1]
                body, sep, weight = inner.rpartition(":")
                try:
                    if not sep or float(weight) >= 0:
                        return None
                except ValueError:
                    return None
                return {"positive": t[:i].rstrip().rstrip(","), "negative": body}
    return None


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
    # The prompt the SAMPLER was given, not whichever encoder comes first: a
    # graph's node order says nothing about which box is which.
    sampler = _first(graph, "*SamplerCustom", "KSampler", "KSamplerAdvanced",
                     "CFGGuider")
    if "positive" not in out and sampler:
        pos = _cond_text(graph, sampler.get("positive"))
        if isinstance(pos, str):
            out["positive"] = pos
            neg = _cond_text(graph, sampler.get("negative"))
            if isinstance(neg, str):
                out["negative"] = neg
    if "positive" not in out:
        texts = [t for inputs in _nodes_of(graph, "CLIPTextEncode")
                 if isinstance(t := _lit(inputs, "text"), str)]
        if texts:
            out["positive"] = texts[0]
            if len(texts) > 1 and texts[1].strip():
                out["negative"] = texts[1]

    for inputs in _nodes_of(graph, "BasicScheduler", "Flux2Scheduler", "*ImageScheduler",
                            "KSampler", "KSamplerAdvanced"):
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
    cfg = _lit(sampler, "cfg", float)
    if cfg is not None:
        out["cfg"] = cfg
    if isinstance(sampler.get("add_noise"), bool):
        out["add_noise"] = sampler["add_noise"]
    for inputs in _nodes_of(graph, "RandomNoise", "*SamplerCustom", "KSampler",
                            "KSamplerAdvanced"):
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
    if out.get("kind") != "video":
        latent = _first(graph, "Empty*LatentImage")
        w, h = _lit(latent, "width", int), _lit(latent, "height", int)
        if w and h:
            out["width"], out["height"] = w, h
        batch = _lit(latent, "batch_size", int)
        if batch:
            out["batch_size"] = batch
        # The toggles are the nodes they insert; a graph without one ran
        # without it, so both are reported either way.
        negpip = any(_nodes_of(graph, "CLIPNegPip", "*NegPip"))
        ms = _first(graph, "ModelSamplingSD3Advanced", "*ModelSampling")
        out["toggles"] = {"negpip": negpip, "model_sampling": bool(ms)}
        if ms:
            out["model_sampling"] = {k: v for k, v in ms.items()
                                     if not isinstance(v, list)}
        if negpip and not (out.get("negative") or "").strip():
            boxes = _unfold_negpip(out.get("positive") or "")
            if boxes:
                out["prompt_boxes"] = boxes

    for inputs in _nodes_of(graph, "UNETLoader", "UnetLoaderGGUF", "OTUNetLoaderW8A8",
                            "CheckpointLoaderSimple", "*CheckpointLoader"):
        name = _lit(inputs, "unet_name") or _lit(inputs, "ckpt_name")
        if isinstance(name, str):
            out["model"] = name
        break

    # Seconds are what the duration control holds; the graph counts frames.
    if out.get("frames") and out.get("fps"):
        out["duration"] = round(out["frames"] / float(out["fps"]), 1)

    return out or None
