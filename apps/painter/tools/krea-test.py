#!/usr/bin/env python3
"""Kroma graph and preference checks; --backend uses CPU-only Comfy node checks."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import registry as R
import graph as G
import userprefs as UP
import fingerprint as FP


def fixture(path, shapes):
    raw = json.dumps({k: {"shape": v, "dtype": "BF16", "data_offsets": [0, 0]}
                      for k, v in shapes.items()}).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)


def models(root):
    fixture(root / "diffusion_models/kroma-v0.3.1-turbo-opd-int8-convrot.safetensors", {
        "txtfusion.projector.weight": [1, 12],
        "txtfusion.layerwise_blocks.0.prenorm.scale": [2560],
        "img_in.weight": [4096, 64], "blocks.0.attn.wq.comfy_quant": [121]})
    fixture(root / "text_encoders/4b.safetensors", {
        "model.layers.0.post_attention_layernorm.weight": [2560],
        "visual.deepstack_merger_list.0.norm.weight": [4096]})
    fixture(root / "vae/qwen_image_vae.safetensors", {"conv1.weight": [32, 16, 1, 1, 1]})


def lora_checks():
    # Match Comfy's Krea2 Diffusers mapping, including SimpleTuner LyCORIS.
    pairs = {
        "transformer_blocks.0.attn.to_q": "blocks.0.attn.wq",
        "transformer_blocks.0.attn.to_out": "blocks.0.attn.wo",
        "transformer_blocks.0.attn.to_out.0": "blocks.0.attn.wo",
        "transformer_blocks.0.ff.up": "blocks.0.mlp.up",
        "text_fusion.refiner_blocks.0.attn.to_gate": "txtfusion.refiner_blocks.0.attn.gate",
        "img_in": "first", "time_embed.linear_1": "tmlp.0",
        "time_embed.linear_2": "tmlp.2", "time_mod_proj": "tproj.1",
        "txt_in.linear_1": "txtmlp.1", "txt_in.linear_2": "txtmlp.3",
        "final_layer.linear": "last.linear",
    }
    with tempfile.TemporaryDirectory(prefix="painter-krea-lora-") as tmp:
        root = Path(tmp)
        models(root)
        path = root / "diffusion_models/kroma-v0.3.1-turbo-opd-int8-convrot.safetensors"
        shapes = {k: v["shape"] for k, v in FP.read_header(str(path)).tensors.items()}
        shapes.update({v + ".weight": [16, 16] for v in pairs.values()})
        fixture(path, shapes)
        for prefix in ("transformer.", "diffusion_model.", "lycoris_"):
            fixture(root / "loras" / (prefix + ".safetensors"), {
                prefix + (k.replace(".", "_") if prefix == "lycoris_" else k) + suffix: [4, 16]
                for k in pairs for suffix in (".lora_A.weight", ".lora_B.weight")})
        fixture(root / "loras/native.safetensors", {"img_in.lora_A.weight": [4, 64]})
        fixture(root / "loras/flux-krea.safetensors", {
            "lora_unet_double_blocks_0_img_attn_qkv.lora_down.weight": [4, 16]})
        reg = R.Registry(tmp, R.Overrides(str(root / "overrides.json")), use_cache=False)
        ok, no = reg.compatible_loras(reg.base_models()[0])
        assert len(ok) == 4 and all(v["score"] == 1 for _, v in ok), (ok, no)
        assert [e.name for e, _ in no] == ["flux-krea.safetensors"]
    print("PASS Krea2 native, Diffusers and LyCORIS compatibility; FLUX adapters excluded")


def graph_checks():
    with tempfile.TemporaryDirectory(prefix="painter-krea-") as tmp:
        root = Path(tmp)
        models(root)
        reg = R.Registry(str(root), R.Overrides(str(root / "overrides.json")), use_cache=False)
        entry = reg.base_models()[0]
        assert entry.family == "krea2" and entry.loader == "OTUNetLoaderW8A8"
        assert not reg.pair(entry)["problems"]
        defaults = reg.defaults_for(entry)
        assert (defaults["steps"], defaults["cfg"], defaults["krea_shift"]) == (8, 1, 1.15)
        for mode in ("native", "manual", "turbo_fixed"):
            for refs in ([], ["remote/first.png", "remote/second.png"]):
                p = dict(positive="red {cube}", negative="blur", system_prompt="Use {literal} braces",
                         reference_images=refs, krea_sampling=mode, krea_shift=2.0,
                         reference_megapixels=.4, width=768, height=1024,
                         steps=1, cfg=1.5, sampler_name="euler_ancestral", scheduler="normal",
                         seed=123, denoise=.8, batch_size=2, add_noise=False,
                         loras=[{"name": "example.safetensors", "strength": .6}])
                built = reg.build(entry, p)
                g = G.Graph(built["prompt"])
                assert g.node("loader")["inputs"]["enable_convrot"] is True
                assert g.node("lora0")["class_type"] == "LoraLoaderModelOnly"
                assert g.node("lora0")["inputs"]["model"] == [g.id_of("loader"), 0]
                assert g.node("lora0")["inputs"]["strength_model"] == .6
                assert g.node("clip")["inputs"]["type"] == "krea2"
                for role in ("encode_pos", "encode_neg"):
                    node = g.node(role)
                    assert node["class_type"] == "PainterKreaEncode"
                    assert node["inputs"]["system_prompt"] == p["system_prompt"]
                    assert node["inputs"]["reference_megapixels"] == .4
                    for i, ref in enumerate(refs):
                        assert node["inputs"][f"images.image_{i}"] == [g.id_of(f"reference_{i}"), 0]
                        assert g.node(f"reference_{i}")["inputs"]["image"] == ref
                assert g.node("encode_pos")["inputs"]["text"] == p["positive"]
                assert g.node("encode_neg")["inputs"]["text"] == p["negative"]
                assert g.node("latent")["inputs"] == {"width": 768, "height": 1024, "batch_size": 2}
                assert g.node("sampler")["inputs"]["noise_seed"] == 123
                assert g.node("sampler")["inputs"]["add_noise"] is False
                assert g.node("scheduler")["inputs"]["steps"] == 1
                assert g.node("scheduler")["inputs"]["denoise"] == .8
                assert g.node("sampler_select")["inputs"]["sampler_name"] == "euler_ancestral"
                assert g.node("scheduler")["inputs"]["model"] == g.node("sampler")["inputs"]["model"]
                if mode == "native":
                    assert not g.has("krea_sampling")
                    assert g.node("sampler")["inputs"]["model"] == [g.id_of("lora0"), 0]
                else:
                    assert g.node("krea_sampling")["inputs"]["mode"] == mode
                    assert g.node("krea_sampling")["inputs"]["model"] == [g.id_of("lora0"), 0]
                assert built["params"]["reference_images"] == refs
                assert built["params"]["system_prompt"] == p["system_prompt"]
                assert not any(n["class_type"] in ("VAEEncode", "ReferenceLatent") for n in g.nodes.values())
        default_graph = G.Graph(reg.build(entry, {})["prompt"])
        assert default_graph.node("encode_neg")["class_type"] == "ConditioningZeroOut"
        assert default_graph.node("encode_neg")["inputs"] == {"conditioning": [default_graph.id_of("encode_pos"), 0]}
        for cfg in (1.0, 1.5):
            for mode in ("native", "turbo_fixed"):
                for refs in ([], ["reference.png"]):
                    request = dict(positive="red cube, (blue:-0.5)", negative="blur",
                                   cfg=cfg, krea_sampling=mode, reference_images=refs,
                                   toggles={"negpip": True},
                                   loras=[{"name": "style.safetensors", "strength": .7}])
                    built = reg.build(entry, request)
                    patched = G.Graph(built["prompt"])
                    patch = patched.node("negpip")
                    assert patch["class_type"] == "ApplyKrea2NegPiP"
                    assert patch["inputs"]["model"] == [patched.id_of("lora0"), 0]
                    assert patch["inputs"]["value_strength"] == 1.0
                    assert patch["inputs"]["debug"] == "off"
                    assert patched.node("encode_pos")["inputs"]["clip"] == [patched.id_of("negpip"), 1]
                    assert patched.node("encode_pos")["inputs"]["text"] == "red cube, (blue:-0.5), (blur:-1)"
                    model_role = "sampler" if mode == "native" else "krea_sampling"
                    assert patched.node(model_role)["inputs"]["model"] == [patched.id_of("negpip"), 0]
                    assert built["params"]["prompt_boxes"]["negative"] == "blur"
                    assert built["params"]["negative"] == ""
                    if cfg == 1:
                        assert patched.node("encode_neg")["class_type"] == "ConditioningZeroOut"
                    else:
                        assert patched.node("encode_neg")["inputs"]["text"] == ""
                    if refs:
                        assert "images.image_0" in patched.node("encode_pos")["inputs"]
        doc = {"genByModel": {entry.name: dict(system_prompt="", krea_sampling="turbo_fixed",
                                                krea_shift=1.3, reference_megapixels=.5)}}
        prefs = UP.params_for(entry.name, doc=doc)
        assert prefs["system_prompt"] == "" and prefs["krea_sampling"] == "turbo_fixed"
        assert prefs["reference_megapixels"] == .5
    print("PASS Kroma detection, pairing, defaults, editable controls, references, LoRAs and saved settings")


def backend_checks():
    # Run from ComfyUI's CPU environment; no model weights or CUDA context.
    sys.path.remove(str(HERE))
    sys.path.insert(0, str(Path(sys.argv[sys.argv.index("--backend") + 1]).resolve()))
    from comfy.cli_args import args
    args.cpu = True
    import torch
    import comfy.model_sampling
    spec = importlib.util.spec_from_file_location("painter_krea", HERE / "comfy_nodes/painter_krea.py")
    node = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(node)
    for cls in (node.PainterKreaEncode, node.PainterKreaSampling):
        assert cls.INPUT_TYPES()
    class Clip:
        def tokenize(self, text, **kwargs):
            self.text, self.kwargs = text, kwargs
            return text
        def encode_from_tokens_scheduled(self, tokens):
            return [[tokens, {}]]
    clip = Clip()
    system = R.load_families()["krea2"]["defaults"]["system_prompt"]
    from comfy.text_encoders.krea2 import KREA2_TEMPLATE
    node.PainterKreaEncode.execute(clip, "red {cube}", system)
    assert clip.text == KREA2_TEMPLATE.format("red {cube}")
    images = {"image_1": torch.ones(1, 64, 32, 3), "image_0": torch.zeros(2, 64, 64, 3)}
    node.PainterKreaEncode.execute(clip, "{literal}", "", .01, images)
    assert clip.text.count("<|image_pad|>") == 3
    assert len(clip.kwargs["images"]) == 3
    assert clip.kwargs["images"][0].sum() == 0 and clip.kwargs["images"][-1].sum() > 0
    assert "{literal}" in clip.text and clip.text.startswith("<|im_start|>system\n<|im_end|>")
    from types import SimpleNamespace
    class Model:
        model = SimpleNamespace(model_config=SimpleNamespace(sampling_settings={"shift": 9.0}))
        def clone(self): return Model()
        def add_object_patch(self, key, value): self.patch = value
    original = Model()
    fixed = node.PainterKreaSampling.execute(original, "turbo_fixed", 5.0)[0]
    expected = comfy.model_sampling.ModelSamplingFlux()
    assert torch.equal(fixed.patch.sigmas, expected.sigmas)
    assert not hasattr(original, "patch")
    manual = node.PainterKreaSampling.execute(original, "manual", 2.0)[0]
    assert manual.patch.shift == 2.0
    print("PASS CPU backend schemas, literal system prompt, batched references and exact Turbo sigma schedule")


if __name__ == "__main__":
    lora_checks()
    graph_checks()
    if "--backend" in sys.argv:
        backend_checks()
