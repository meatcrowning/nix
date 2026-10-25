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
            for layers in ('24, 26', ''):
                settings = dict(slg_single_layers=layers, slg_start_percent=.125, slg_end_percent=.875)
                custom = reg.build(entry, settings)
                inputs = G.Graph(custom['prompt']).node('moss_guidance')['inputs']
                assert inputs['single_layers'] == layers and inputs['double_layers'] == ''
                assert inputs['start_percent'] == .125 and inputs['end_percent'] == .875
                assert all(custom['params'][key] == value for key, value in settings.items())
                import userprefs
                doc = {'genByModel': json.dumps({entry.name: settings})}
                assert all(userprefs.params_for(entry.name, 'image', doc)[key] == value
                           for key, value in settings.items())
            for invalid in ({'slg_single_layers': '-1'}, {'slg_single_layers': '22oops'},
                            {'slg_start_percent': .9, 'slg_end_percent': .1},
                            {'slg_end_percent': float('nan')}, {'slg_start_percent': -1}):
                try:
                    reg.build(entry, invalid)
                except G.GraphError:
                    pass
                else:
                    raise AssertionError('invalid SLG settings accepted')
            weighted = reg.build(entry, dict(positive="A (red:1.5) cap", negative="blur",
                                             toggles={"negpip": True, "model_sampling": True}))
            graph = G.Graph(weighted["prompt"])
            assert graph.node("negpip")["class_type"] == "CLIPNegPip"
            assert graph.node("negpip")["inputs"]["model"] == [graph.id_of("moss_guidance"), 0]
            assert graph.node("encode_pos")["inputs"]["clip"] == [graph.id_of("negpip"), 1]
            assert graph.node("encode_pos")["inputs"]["text"] == "A (red:1.5) cap, (blur:-1)"
            assert graph.node("encode_neg")["inputs"]["text"] == ""
            assert not graph.has("model_sampling")
            for role in ("scheduler", "sampler"):
                assert graph.node(role)["inputs"]["model"] == [graph.id_of("negpip"), 0]
            assert weighted["params"]["toggles"] == {"negpip": True, "model_sampling": False}
            assert weighted["params"]["prompt_boxes"] == {"positive": "A (red:1.5) cap", "negative": "blur"}
            import moss_layout
            layout = moss_layout.fresh(1024, 1024, "A poster")
            editor = moss_layout.Editor(layout)
            editor.add('object')['caption'] = '(hat:1.5)'
            layout = editor.doc
            layout['enabled'] = True
            weighted_layout = reg.build(entry, dict(positive="A (red:1.5) cap", negative="blur",
                                                    moss_layout=layout, toggles={"negpip": True}))
            compiled = json.loads(G.Graph(weighted_layout['prompt']).node('encode_pos')['inputs']['text'])
            assert compiled['summary']['caption'] == "A (red:1.5) cap, (blur:-1)"
            for p in ({"edit": True}, {"loras": [{"name": "wrong.safetensors"}]}):
                try:
                    reg.build(entry, p)
                except G.GraphError:
                    pass
                else:
                    raise AssertionError("unsupported MOSS pipeline accepted")
        # The correction is automatic only for known stock SFT filenames.
        stock = root / "diffusion_models/moss_image_sft_int8_convrot.safetensors"
        stock.write_bytes((root / "diffusion_models/moss-sft-int8.safetensors").read_bytes())
        reg.scan(use_cache=False)
        entry = reg.find(stock.name)
        try:
            reg.build(entry, {})
        except G.GraphError as exc:
            assert "Destripe is missing" in str(exc)
        else:
            raise AssertionError("missing correction silently ignored")
        assert not G.Graph(reg.build(entry, {"moss_destripe_strength": 0})["prompt"]).has("moss_destripe")
        fixture(root / "loras/moss_sft_destripe_top64_bf16.safetensors", {
            "diffusion_model.layers.24.proj.ffn_up_gate.lora_down.weight": [1, 3072],
            "diffusion_model.layers.24.proj.ffn_up_gate.lora_up.weight": [8192, 1]})
        reg.scan(use_cache=False)
        entry = reg.find(stock.name)
        for width, strength in ((768, 1.0), (1024, 1.5), (1536, 1.5)):
            for negpip in (False, True):
                built = reg.build(entry, {"width": width, "height": 1024,
                                          "toggles": {"negpip": negpip}})
                graph = G.Graph(built["prompt"])
                fix = graph.node("moss_destripe")
                assert fix["class_type"] == "LoraLoaderModelOnly"
                assert fix["inputs"]["strength_model"] == strength
                assert fix["inputs"]["model"] == [graph.id_of("loader"), 0]
                assert graph.node("moss_guidance")["inputs"]["model"] == [graph.id_of("moss_destripe"), 0]
                assert built["params"]["moss_destripe_strength"] == strength
                assert built["params"]["moss_destripe_lora"] == fix["inputs"]["lora_name"]
                assert graph.node("vae")["inputs"]["vae_name"] == "moss-image-vae.safetensors"
        for invalid in (-1, 3, float('nan'), 'bad'):
            try:
                reg.build(entry, {"moss_destripe_strength": invalid})
            except G.GraphError:
                pass
            else:
                raise AssertionError("invalid Destripe strength accepted")
        for name in ("moss-base-int8.safetensors", "moss-sft-int8.safetensors"):
            assert not G.Graph(reg.build(reg.find(name), {})["prompt"]).has("moss_destripe")
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
