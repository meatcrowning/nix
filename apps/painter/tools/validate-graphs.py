#!/usr/bin/env python3
"""Prove the universal graph survives every family and every toggle combination.

Builds the graph for each base model, for all four on/off combinations of the two
optional nodes, and validates each against the live /object_info.  Also checks the
splice-out logic structurally: with NegPip removed the positive encode must fall
back to the raw CLIP, and with ModelSampling removed both the sampler and the
scheduler must read the model source directly.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import graph as G  # noqa: E402
import registry as R  # noqa: E402

PROMPT = "a red cube on a white table"
MULTILINE = "line one\n\nline two\twith   spaces\nline three"


def _roles_of(prompt):
    roles = {}
    for nid, node in prompt.items():
        r = (node.get("_meta") or {}).get("painter_role")
        if r:
            roles[r] = nid
    return roles


def check_dangling(prompt):
    """Every link must point at a node that still exists."""
    return [f"{nid}.{key} dangles to removed node {val[0]}"
            for nid, node in prompt.items()
            for key, val in node["inputs"].items()
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str)
            and val[0] not in prompt]


def check_video(built, want_image, want_last=False):
    """The video template's two modes, which differ by three nodes.

    Image-to-video reads its frame size out of the dropped image; text-to-video
    drops that whole chain, so the check is that the size is two plain numbers
    and that nothing is left pointing at a node that went.
    """
    prompt = built["prompt"]
    roles = _roles_of(prompt)
    problems = []
    video = prompt[roles["video"]]["inputs"]
    if want_image:
        for role in ("load_image", "scale_image", "image_size"):
            if role not in roles:
                problems.append(f"image-to-video is missing {role}")
        if not isinstance(video.get("width"), list):
            problems.append("image-to-video should take its width from the image")
        if not isinstance(video.get("first_frame"), list):
            problems.append("image-to-video is not wired to a first frame")
        # The frame to end on is its own LoadImage, wired only when dropped.
        if want_last and not isinstance(video.get("last_frame"), list):
            problems.append("a clip with a last frame is not wired to one")
        if want_last and "load_image_last" not in roles:
            problems.append("a clip with a last frame is missing load_image_last")
        if not want_last and "last_frame" in video:
            problems.append("a clip with no last frame carries a last_frame")
        if not want_last and "load_image_last" in roles:
            problems.append("a clip with no last frame still carries load_image_last")
    else:
        for role in ("load_image", "load_image_last", "scale_image", "image_size"):
            if role in roles:
                problems.append(f"text-to-video still carries {role}")
        if "first_frame" in video:
            problems.append("text-to-video still carries a first_frame input")
        if not isinstance(video.get("width"), int) or not isinstance(video.get("height"), int):
            problems.append("text-to-video needs plain width/height numbers")
    if prompt[roles["create_video"]]["inputs"].get("audio") is None:
        problems.append("the audio track is not muxed into the video")
    return problems + check_dangling(prompt)


def check_structure(built, toggles, fam):
    """Structural assertions the validator cannot make for us."""
    prompt = built["prompt"]
    roles = _roles_of(prompt)
    problems = []

    if toggles.get("negpip"):
        if "negpip" not in roles:
            problems.append("negpip enabled but absent from the graph")
        else:
            src = prompt[roles["encode_pos"]]["inputs"]["clip"]
            if src[0] != roles["negpip"] or src[1] != 1:
                problems.append("positive encode is not reading the NegPip CLIP output")
            neg = prompt[roles["encode_neg"]]["inputs"]["clip"]
            if neg[0] == roles["negpip"]:
                problems.append("negative encode should read the raw CLIP, not NegPip")
    else:
        if "negpip" in roles:
            problems.append("negpip disabled but still present")
        else:
            pos = prompt[roles["encode_pos"]]["inputs"]["clip"]
            neg = prompt[roles["encode_neg"]]["inputs"]["clip"]
            if pos != neg:
                problems.append(
                    f"with NegPip removed both encodes should share a CLIP source, got {pos} vs {neg}"
                )

    if toggles.get("model_sampling"):
        if "model_sampling" not in roles:
            problems.append("model_sampling enabled but absent")
        else:
            ms = roles["model_sampling"]
            for consumer in ("sampler", "scheduler"):
                if prompt[roles[consumer]]["inputs"]["model"][0] != ms:
                    problems.append(f"{consumer} does not read the ModelSampling output")
    else:
        if "model_sampling" in roles:
            problems.append("model_sampling disabled but still present")
        else:
            a = prompt[roles["sampler"]]["inputs"]["model"]
            b = prompt[roles["scheduler"]]["inputs"]["model"]
            if a != b:
                problems.append(
                    f"with ModelSampling removed sampler and scheduler should share a "
                    f"model source, got {a} vs {b}"
                )

    return problems + check_dangling(prompt)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--offline", action="store_true", help="skip /object_info checks")
    ap.add_argument("--root", default=R.MODEL_ROOT)
    args = ap.parse_args(argv)

    oi = None
    if not args.offline:
        try:
            oi = G.fetch_object_info(args.url)
        except Exception as exc:  # noqa: BLE001
            print(f"could not reach {args.url}: {exc}", file=sys.stderr)
            return 3

    reg = R.Registry(args.root)
    failures = 0
    combos = [
        {"negpip": a, "model_sampling": b}
        for a in (False, True)
        for b in (False, True)
    ]

    print("=== toggle matrix ===")
    for entry in reg.base_models():
        fam = reg.family_of(entry)
        if (fam or {}).get("kind") == "video":
            continue          # no toggles, no encodes; checked in its own section
        line = f"  {entry.name[:50]:<52}"
        for toggles in combos:
            tag = ("N" if toggles["negpip"] else "-") + ("M" if toggles["model_sampling"] else "-")
            try:
                built = reg.build(
                    entry,
                    {"positive": PROMPT, "negative": "", "seed": 1, "steps": 4,
                     "toggles": toggles},
                    object_info=oi,
                )
                probs = check_structure(built, toggles, fam)
                if probs:
                    raise G.ValidationError(probs)
                line += f" {tag}:ok"
            except (G.GraphError, G.ValidationError) as exc:
                failures += 1
                line += f" {tag}:FAIL"
                line += f"\n        {tag}: {exc}"
        print(line)

    print("\n=== video ===")
    for entry in reg.base_models():
        fam = reg.family_of(entry) or {}
        if fam.get("kind") != "video":
            continue
        line = f"  {entry.name[:50]:<52}"
        for tag, params in (
            ("i2v", {"use_input_image": True, "input_image": "probe.png"}),
            ("fl2v", {"use_input_image": True, "input_image": "probe.png",
                      "use_last_frame": True, "last_image": "probe.png"}),
            ("t2v", {"use_input_image": False}),
        ):
            try:
                built = reg.build(
                    entry,
                    {"positive": PROMPT, "seed": 1, "steps": 4, "duration": 5.0, **params},
                    object_info=oi,
                )
                probs = check_video(built, params["use_input_image"],
                                    params.get("use_last_frame", False))
                if probs:
                    raise G.ValidationError(probs)
                line += f" {tag}:ok({built['params']['frames']}f)"
            except (G.GraphError, G.ValidationError) as exc:
                failures += 1
                line += f" {tag}:FAIL\n        {tag}: {exc}"
        print(line)

    print("\n=== prompt transforms ===")
    for entry in reg.base_models():
        fam = reg.family_of(entry) or {}
        if fam.get("kind") == "video":
            continue          # one prompt, no negative, no transform
        want_flat = fam.get("prompt_transform") == "single_line"
        built = reg.build(entry, {"positive": MULTILINE, "negative": MULTILINE, "seed": 1})
        sent = built["params"]["positive"]
        flat = "\n" not in sent and "  " not in sent
        ok = flat if want_flat else (sent == MULTILINE)
        if not ok:
            failures += 1
        if want_flat or not ok:
            print(f"  {'OK ' if ok else 'FAIL'} {entry.name[:44]:<46} "
                  f"transform={fam.get('prompt_transform')} -> {sent!r}")
    print(f"  (other families pass the prompt through unchanged)")

    print(f"\n{'PASS' if not failures else f'{failures} FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
