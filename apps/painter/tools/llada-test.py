#!/usr/bin/env python3
"""Header/graph regressions; no torch, GPU, backend, or user state required."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import graph as G
import registry as R

KEYS = {"model.diffusion_model." + k: [16, 16] for k in (
    "all_x_embedder.1-1.weight", "noise_refiner.0.attention.to_q.weight",
    "sigvq_refiner.0.attention.to_q.weight")}
KEYS["vae.decoder.conv_in.weight"] = [8, 16, 3, 3]


def fixture(path, variant="base"):
    tensors = {k: {"shape": v, "dtype": "BF16", "data_offsets": [0, 512]}
               for k, v in KEYS.items()}
    tensors["__metadata__"] = {"config": json.dumps({"llada_image": {"variant": variant}})}
    raw = json.dumps(tensors).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + bytes(512))


def main():
    spec = importlib.util.spec_from_file_location("validate_graphs", Path(__file__).with_name("validate-graphs.py"))
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    with tempfile.TemporaryDirectory(prefix="painter-llada-") as tmp:
        root = Path(tmp)
        path = root / "checkpoints/renamed.safetensors"
        fixture(path)
        reg = R.Registry(str(root), R.Overrides(str(root/"overrides.json")), use_cache=False)
        entry = reg.base_models()[0]
        assert entry.family == "llada_image_ckpt" and entry.dims["variant"] == "base"
        assert not reg.pair(entry)["problems"]
        for edit in (False, True):
            for scale in (False, True):
                built = reg.build(entry, {"edit": edit, "input_image": "source.png",
                    "editNoScale": scale, "steps": 1, "cfg": 5.0, "seed": 42,
                    "positive": "a fox", "negative": "blur", "width": 512, "height": 512,
                    "sampler_name": "heun", "scheduler": "simple", "denoise": .2,
                    "toggles": {"negpip": True, "model_sampling": True}})
                roles = checks._roles_of(built["prompt"])
                p = built["params"]
                assert p["steps"] == 1 and p["cfg"] == 5 and p["denoise"] == .2
                assert p["sampler_name"] == "heun" and p["scheduler"] == "simple"
                assert built["prompt"][roles["scheduler"]]["inputs"]["denoise"] == .2
                assert built["prompt"][roles["sampler_select"]]["inputs"]["sampler_name"] == "heun"
                assert not p["toggles"]["negpip"] and "model_sampling" not in roles
                assert not checks.check_dangling(built["prompt"])
                assert p["prompt_boxes"] == {"positive": "a fox", "negative": "blur"}
                if edit:
                    assert not checks.check_edit(built)
                    assert "width" not in p and "batch_size" not in p
                else:
                    assert not checks.check_structure(built, p["toggles"], reg.family_of(entry))
                    assert built["prompt"][roles["latent"]]["class_type"] == "EmptyFlux2LatentImage"
        for denoise in (0, .5, 1):
            built = reg.build(entry, {"steps": 10, "denoise": denoise})
            roles = checks._roles_of(built["prompt"])
            sched = built["prompt"][roles["scheduler"]]
            assert sched["class_type"] == "T8LLaDAImageScheduler"
            assert sched["inputs"]["steps"] == (20 if denoise == .5 else 10)
            if denoise < 1:
                split = built["prompt"][roles["denoise_sigmas"]]
                assert split["inputs"]["step"] == 10
            else:
                assert "denoise_sigmas" not in roles
        for params in ({"edit": True}, {"edit": True, "input_images": ["a", "b"]}, {"loras": [{"name": "bad"}]}, {"denoise": -1}, {"steps": 300, "denoise": .01}):
            try:
                reg.build(entry, params)
            except G.GraphError:
                pass
            else:
                raise AssertionError(f"Should reject {params}")
        for variant in ("turbo", "unknown"):
            entry.dims["variant"] = variant
            try:
                reg.build(entry, {})
            except G.GraphError:
                pass
            else:
                raise AssertionError("Base sampler must not run another variant")
        print("PASS LLaDA detection, t2i/edit graphs, native controls, and refusals")


if __name__ == "__main__":
    main()
