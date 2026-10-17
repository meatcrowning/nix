#!/usr/bin/env python3
"""MOSS header detection, component pairing and generation wiring; no inference."""
import json
from pathlib import Path
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fingerprint as F
import graph as G
import registry as R


def fixture(path, shapes):
    raw = json.dumps({k: {"shape": v, "dtype": "BF16", "data_offsets": [0, 0]}
                      for k, v in shapes.items()}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)


def models(root):
    for name in ("moss-base-int8", "moss-sft-int8"):
        fixture(root / "diffusion_models" / (name + ".safetensors"), {
            "video_embedder.bias": [3072], "text_embedder.proj.weight": [3072, 4096],
            "shared_block_modulation.weight": [18432, 3072],
            "layers.0.q_norm.weight": [128], "final_linear_video.weight": [128, 3072],
            "layers.0.proj.q.comfy_quant": [1]})
    fixture(root / "text_encoders/qwen35.safetensors", {
        "model.language_model.layers.0.linear_attn.A_log": [32],
        "model.language_model.layers.0.input_layernorm.weight": [4096]})
    fixture(root / "vae/moss-image-vae.safetensors", {
        "decoder.conv_in.weight": [384, 32, 3, 3], "bn.running_mean": [128]})


def main():
    with tempfile.TemporaryDirectory(prefix="painter-moss-test-") as tmp:
        root = Path(tmp)
        models(root)
        reg = R.Registry(str(root), R.Overrides(str(root / "overrides.json")), use_cache=False)
        assert len(reg.base_models()) == 2
        assert all(m["family"] != "moss_image" for m in R.MODES)
        for entry in reg.base_models():
            assert entry.family == "moss_image" and entry.quant == "comfy_quant"
            assert not reg.pair(entry)["problems"]
            fam = reg.family_of(entry)
            assert not fam["supports_patches"] and not fam["supports_loras"]
            assert not fam.get("edit") and not fam.get("reference_images")
            for overrides in ({}, {"steps": 23, "cfg": 4.5, "sampler_name": "heun",
                                   "scheduler": "beta", "denoise": .8, "add_noise": False}):
                p = dict(positive="A mountain\nwith a lake", negative="blur, text", seed=42,
                         width=1280, height=720, batch_size=2, **overrides)
                built = reg.build(entry, p)
                graph = built["prompt"]
                roles = {n["_meta"]["painter_role"]: key for key, n in graph.items()}
                node = lambda role: graph[roles[role]]
                inputs = lambda role: node(role)["inputs"]
                assert node("loader")["class_type"] == "UNETLoader"
                assert node("clip")["class_type"] == "CLIPLoader"
                assert inputs("clip")["type"] == "moss_image"
                assert node("latent")["class_type"] == "EmptyFlux2LatentImage"
                assert inputs("latent") == {"width": 1280, "height": 720, "batch_size": 2}
                assert inputs("encode_pos")["text"] == p["positive"]
                assert inputs("encode_neg")["text"] == p["negative"]
                assert inputs("encode_neg")["clip"] == [roles["clip"], 0]
                assert inputs("moss_guidance")["single_layers"] == "22"
                assert inputs("moss_guidance")["model"] == [roles["loader"], 0]
                assert not any(n["class_type"] == "ModelSamplingSD3" for n in graph.values())
                for role in ("scheduler", "sampler"):
                    assert inputs(role)["model"] == [roles["moss_guidance"], 0]
                assert inputs("sampler")["noise_seed"] == 42
                assert inputs("sampler")["cfg"] == overrides.get("cfg", 3)
                assert inputs("sampler")["add_noise"] == overrides.get("add_noise", True)
                assert inputs("sampler_select")["sampler_name"] == overrides.get("sampler_name", "euler")
                assert inputs("scheduler")["steps"] == overrides.get("steps", 50)
                assert inputs("scheduler")["scheduler"] == overrides.get("scheduler", "sgm_uniform")
                assert inputs("scheduler")["denoise"] == overrides.get("denoise", 1)
                assert "model_sampling" not in roles and "negpip" not in roles
                assert built["params"]["prompt_boxes"] == {k: p[k] for k in ("positive", "negative")}
            for p in ({"edit": True}, {"loras": [{"name": "wrong.safetensors"}]}):
                try:
                    reg.build(entry, p)
                except G.GraphError:
                    pass
                else:
                    raise AssertionError("unsupported MOSS pipeline accepted")
        # Architecture detection survives renaming and doesn't steal other Qwens.
        h = F.Header({"language_model.layers.0.linear_attn.A_log": {"shape": [32]},
                      "language_model.layers.0.input_layernorm.weight": {"shape": [4096]}}, {}, "safetensors")
        assert F.detect_text_encoder(h)[0] == "QWEN35_9B"
        (root / "text_encoders/qwen35.safetensors").unlink()
        reg.scan(use_cache=False)
        assert reg.pair(reg.base_models()[0])["problems"]
    print("PASS MOSS Base/SFT detection, pairing, defaults, prompt and sampler wiring")


if __name__ == "__main__":
    main()
