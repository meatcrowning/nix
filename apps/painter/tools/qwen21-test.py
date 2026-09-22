#!/usr/bin/env python3
"""Check Qwen 2.1 detection and graph wiring without inference or user state."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import graph as G
import registry as R


def fixture(path, shapes):
    raw = json.dumps({k: {"shape": v, "dtype": "BF16", "data_offsets": [0, 0]}
                      for k, v in shapes.items()}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)


def main():
    spec = importlib.util.spec_from_file_location("checks", Path(__file__).with_name("validate-graphs.py"))
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    with tempfile.TemporaryDirectory(prefix="painter-qwen21-") as tmp:
        root = Path(tmp)
        fixture(root / "diffusion_models/renamed.safetensors", {
            "txt_in.text_norm.weight": [4096], "modulation.1.weight": [24576, 4096],
            "transformer_blocks.0.attn.norm_q.weight": [128],
            "img_in.weight": [4096, 64], "proj_out.weight": [64, 4096],
            "transformer_blocks.0.img_mlp.gate_up.weight": [24576, 4096],
            "transformer_blocks.0.img_mlp.gate_up.comfy_quant": [1]})
        encoder = root / "text_encoders/renamed.safetensors"
        def te(hidden):
            fixture(encoder, {"model.layers.0.post_attention_layernorm.weight": [hidden],
                "visual.deepstack_merger_list.0.norm.weight": [4608]})
        te(4096)
        fixture(root / "vae/renamed.safetensors", {
            "conv1.weight": [128, 128, 1, 1, 1],
            "decoder.head.2.weight": [4, 144, 1, 3, 3],
            "decoder.upsamples.0.upsamples.0.residual.2.weight": [1152, 1152, 1, 3, 3]})
        reg = R.Registry(str(root), R.Overrides(str(root / "overrides.json")), use_cache=False)
        entry = reg.base_models()[0]
        assert entry.family == "qwen_image21" and entry.quant == "comfy_quant"
        assert reg.pair(entry)["vae"].family == "qwen_image21"
        for edit in (False, True):
            for no_scale in (False, True):
                p = {"positive": "a red cube", "negative": "blur", "seed": 987654321,
                     "steps": 37, "cfg": 3.2, "sampler_name": "heun",
                     "scheduler": "linear_quadratic", "denoise": .8, "add_noise": False,
                     "width": 960, "height": 1280, "edit": edit,
                     "input_images": ["first.png", "second.png"], "editNoScale": no_scale,
                     "editMegapixels": 1.5, "toggles": {"negpip": True, "model_sampling": True}}
                built = reg.build(entry, p)
                assert not checks.check_qwen21(built, edit)
                roles = checks._roles_of(built["prompt"])
                node = lambda role: built["prompt"][roles[role]]["inputs"]
                assert built["prompt"][roles["loader"]]["class_type"] == "UNETLoader"
                assert node("clip")["type"] == "qwen_image"
                assert node("encode_pos")["negative_prompt"] == "blur"
                assert "text" not in node("encode_pos")
                assert node("sampler")["noise_seed"] == p["seed"]
                assert node("sampler")["cfg"] == p["cfg"]
                assert node("sampler")["add_noise"] is False
                assert node("sampler_select")["sampler_name"] == "heun"
                assert node("scheduler")["steps"] == 37
                assert node("scheduler")["scheduler"] == "linear_quadratic"
                assert node("scheduler")["denoise"] == .8
                if edit:
                    assert "images.image_2" in node("encode_pos")
                    assert node("encode_pos")["resolution"] == (0 if no_scale else 1248)
                    assert "width" not in built["params"]
                else:
                    assert node("latent")["width"] == 960
                assert built["params"]["prompt_boxes"] == {"positive": "a red cube", "negative": "blur"}
        for images in ([], ["x"] * 17):
            try:
                reg.build(entry, {"edit": True, "input_images": images})
            except G.GraphError:
                pass
            else:
                raise AssertionError("invalid reference count accepted")
        te(5120)  # the installed MiniMax encoder must never substitute for 8B
        reg.scan(use_cache=False)
        assert reg.pair(reg.base_models()[0])["problems"]
    schema = {"Q": {"input": {"required": {"images": ["COMFY_AUTOGROW_V3", {
        "template": {"input": {"required": {"image": ["IMAGE", {}]}},
                     "names": ["image_1", "image_2"], "min": 0}}]}}}}
    assert not G.validate({"1": {"class_type": "Q", "inputs": {}}}, schema)
    assert not G.validate({"1": {"class_type": "Q", "inputs": {"images.image_2": ["1", 0]}}}, schema)
    assert G.validate({"1": {"class_type": "Q", "inputs": {"images.image_3": ["1", 0]}}}, schema)
    print("PASS Qwen 2.1 detection, pairing, sampler wiring, references, and V3 validation")


if __name__ == "__main__":
    main()
