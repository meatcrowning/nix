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


def check_structure(built, toggles, fam):
    """Structural assertions the validator cannot make for us."""
    prompt = built["prompt"]
    roles = {}
    for nid, node in prompt.items():
        r = (node.get("_meta") or {}).get("painter_role")
        if r:
            roles[r] = nid
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

    # Every link must point at a node that still exists.
    for nid, node in prompt.items():
        for key, val in node["inputs"].items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
                if val[0] not in prompt:
                    problems.append(f"{nid}.{key} dangles to removed node {val[0]}")
    return problems


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

    print("\n=== prompt transforms ===")
    for entry in reg.base_models():
        fam = reg.family_of(entry) or {}
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
