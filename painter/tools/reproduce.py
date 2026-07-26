#!/usr/bin/env python3
"""Check painter rebuilds the workflows this app was modelled on.

Two references, both exported from ComfyUI by hand:

  k2_raw_00108_.json   Krea 2, plain KSampler, the txtfusion .diff LoRA
  ComfyUI_12225_.json  Anima, SamplerCustom + CLIPNegPip + ModelSamplingSD3Advanced

Neither can be compared naively:

* the Krea 2 file calls rgthree's `ResolutionSelector`, which is installed
  nowhere, so its width/height are folded to the literals it would have produced;
* the Anima file exported with nodes 39 and 40 stripped of their `class_type`
  (they show up as `"UNKNOWN": 1`), so they are restored from cte's live template;
* both route values through pass-through nodes painter inlines
  (`PrimitiveStringMultiline`, `Seed (rgthree)`).

So the comparison constant-folds those indirections on both sides and then
compares the effective inputs of the nodes that actually determine the image.
Structural differences that cannot change a pixel are reported, not failed.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import graph as G  # noqa: E402
import registry as R  # noqa: E402

DOWNLOADS = "/home/lam/Downloads"

# Nodes whose only job is to hand a literal to another node.
PASSTHROUGH = {
    "PrimitiveStringMultiline": "value",
    "PrimitiveString": "value",
    "Seed (rgthree)": "seed",
    "PrimitiveInt": "value",
    "PrimitiveFloat": "value",
}

# What actually determines the image.
COMPARED = {
    "UNETLoader": ["unet_name", "weight_dtype"],
    "UnetLoaderGGUF": ["unet_name"],
    "OTUNetLoaderW8A8": ["unet_name", "model_type"],
    "CheckpointLoaderSimple": ["ckpt_name"],
    "CLIPLoader": ["clip_name", "type"],
    "VAELoader": ["vae_name"],
    "LoraLoaderModelOnly": ["lora_name", "strength_model"],
    "CLIPTextEncode": ["text"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "KSampler": ["seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "KSamplerSelect": ["sampler_name"],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "SamplerCustom": ["noise_seed", "cfg", "add_noise"],
    "ModelSamplingSD3Advanced": ["shift_start", "shift_end", "start_percent",
                                 "end_percent", "curve", "outside_window", "multiplier"],
    "CLIPNegPip": [],
}


def fold(prompt: dict) -> dict:
    """Replace links to pass-through nodes with the literal they carry."""
    out = copy.deepcopy(prompt)
    literals = {}
    for nid, node in out.items():
        key = PASSTHROUGH.get(node.get("class_type"))
        if key is not None:
            literals[nid] = (node.get("inputs") or {}).get(key)
    for node in out.values():
        for k, v in list((node.get("inputs") or {}).items()):
            if isinstance(v, list) and len(v) == 2 and v[0] in literals:
                node["inputs"][k] = literals[v[0]]
    for nid in literals:
        out.pop(nid, None)
    return out


def effective(prompt: dict) -> dict:
    """{class_type: [ {key: value} ]} for the nodes that shape the image."""
    folded = fold(prompt)
    out = {}
    for node in folded.values():
        cls = node.get("class_type")
        if cls not in COMPARED:
            continue
        vals = {}
        for key in COMPARED[cls]:
            if key in (node.get("inputs") or {}):
                vals[key] = node["inputs"][key]
        out.setdefault(cls, []).append(vals)
    for lst in out.values():
        lst.sort(key=lambda d: json.dumps(d, sort_keys=True, default=str))
    return out


def compare(ref: dict, got: dict):
    """Differences that could change the image."""
    problems = []
    a, b = effective(ref), effective(got)

    # KSampler and SamplerCustom express the same settings differently.
    def normalise(d):
        n = {k: v for k, v in d.items()}
        ks = n.pop("KSampler", None)
        if ks:
            for e in ks:
                n.setdefault("KSamplerSelect", []).append(
                    {"sampler_name": e.get("sampler_name")})
                n.setdefault("BasicScheduler", []).append(
                    {"scheduler": e.get("scheduler"), "steps": e.get("steps"),
                     "denoise": e.get("denoise")})
                n.setdefault("SamplerCustom", []).append(
                    {"noise_seed": e.get("seed"), "cfg": e.get("cfg"), "add_noise": True})
        return n

    a, b = normalise(a), normalise(b)
    for cls in sorted(set(a) | set(b)):
        ea, eb = a.get(cls, []), b.get(cls, [])
        if ea != eb:
            problems.append(f"{cls}:\n      reference {json.dumps(ea, default=str)}"
                            f"\n      painter   {json.dumps(eb, default=str)}")
    return problems


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}


def krea2_reference():
    """The k2 workflow with ResolutionSelector folded to the size it produced."""
    wf = load(os.path.join(DOWNLOADS, "k2_raw_00108_.json"))
    # ResolutionSelector: 2:3 at 2.7MP, multiple of 8.
    w, h = R.calc_dims("2:3", 2.7, 8)
    wf.pop("49", None)
    wf["52"]["inputs"]["width"] = w
    wf["52"]["inputs"]["height"] = h
    return wf, {"width": w, "height": h}


def anima_reference():
    """The Anima export, with the two class-stripped nodes restored."""
    wf = load(os.path.join(DOWNLOADS, "ComfyUI_12225_.json"))
    tmpl = load("/home/lam/Projects/cte/app/t2i_newest.json")
    for nid in ("39", "40"):
        if nid in wf and not wf[nid].get("class_type"):
            wf[nid]["class_type"] = tmpl[nid]["class_type"]
            merged = dict(tmpl[nid]["inputs"])
            merged.update({k: v for k, v in wf[nid]["inputs"].items() if k != "UNKNOWN"})
            wf[nid]["inputs"] = merged
    return wf, {}


CASES = {
    "krea2": {
        "build": krea2_reference,
        "model": "krea2_raw_fp8_scaled.safetensors",
        "params": lambda wf, extra: {
            "positive": wf["61"]["inputs"]["value"],
            "negative": wf["71"]["inputs"]["value"],
            "seed": wf["67"]["inputs"]["seed"],
            "steps": wf["53"]["inputs"]["steps"],
            "cfg": wf["53"]["inputs"]["cfg"],
            "sampler_name": wf["53"]["inputs"]["sampler_name"],
            "scheduler": wf["53"]["inputs"]["scheduler"],
            "denoise": wf["53"]["inputs"]["denoise"],
            "width": extra["width"], "height": extra["height"],
            "loras": [{"name": wf["78"]["inputs"]["lora_name"],
                       "strength": wf["78"]["inputs"]["strength_model"]}],
            "toggles": {"negpip": False, "model_sampling": False},
        },
    },
    "anima": {
        "build": anima_reference,
        "model": "anima-base-v1.0.safetensors",
        "params": lambda wf, extra: {
            "positive": wf["5"]["inputs"]["text"],
            "negative": wf["6"]["inputs"]["text"],
            "seed": wf["4"]["inputs"]["noise_seed"],
            "cfg": wf["4"]["inputs"]["cfg"],
            "steps": wf["14"]["inputs"]["steps"],
            "scheduler": wf["14"]["inputs"]["scheduler"],
            "denoise": wf["14"]["inputs"]["denoise"],
            "sampler_name": wf["11"]["inputs"]["sampler_name"],
            "width": wf["41"]["inputs"]["width"],
            "height": wf["41"]["inputs"]["height"],
            "toggles": {"negpip": True, "model_sampling": True},
            "model_sampling": {k: v for k, v in wf["39"]["inputs"].items()
                               if k != "model"},
        },
    },
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", choices=sorted(CASES) + ["all"], default="all")
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--dump", metavar="DIR")
    args = ap.parse_args(argv)

    try:
        oi = G.fetch_object_info(args.url)
    except Exception:  # noqa: BLE001 - the structural comparison still works
        oi = None
        print("(backend unreachable: skipping /object_info validation)\n")

    reg = R.Registry()
    names = sorted(CASES) if args.case == "all" else [args.case]
    failures = 0

    for name in names:
        case = CASES[name]
        ref, extra = case["build"]()
        entry = reg.find(case["model"])
        if entry is None:
            print(f"{name}: model {case['model']} not found")
            failures += 1
            continue
        params = case["params"](ref, extra)
        built = reg.build(entry, params, object_info=oi)

        print(f"=== {name} ===")
        print(f"  model    {entry.name}")
        print(f"  encoder  {getattr(built['pairing']['encoder'], 'name', '(bundled)')}")
        print(f"  vae      {getattr(built['pairing']['vae'], 'name', '(bundled)')}")

        problems = compare(ref, built["prompt"])
        if problems:
            failures += 1
            print(f"  MISMATCH in {len(problems)} node class(es):")
            for p in problems:
                print(f"    {p}")
        else:
            print("  effective inputs match the reference exactly")

        # Report the structural differences we expect, so they stay visible.
        ref_classes = {n["class_type"] for n in ref.values() if n.get("class_type")}
        got_classes = {n["class_type"] for n in built["prompt"].values()}
        only_ref = ref_classes - got_classes
        only_got = got_classes - ref_classes
        if only_ref or only_got:
            print(f"  structural (cannot affect pixels): reference-only "
                  f"{sorted(only_ref) or '-'}, painter-only {sorted(only_got) or '-'}")

        if args.dump:
            os.makedirs(args.dump, exist_ok=True)
            with open(os.path.join(args.dump, f"{name}-reference.json"), "w") as fh:
                json.dump(ref, fh, indent=1, sort_keys=True)
            with open(os.path.join(args.dump, f"{name}-painter.json"), "w") as fh:
                json.dump(built["prompt"], fh, indent=1, sort_keys=True)
        print()

    print("PASS" if not failures else f"{failures} case(s) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
