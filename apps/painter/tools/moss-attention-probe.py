#!/usr/bin/env python3
"""CPU-only MOSS attention feasibility probe against an existing Comfy checkout.

Run with Comfy's Python: moss-attention-probe.py --comfy /path/to/ComfyUI.
Uses tiny random MOSS weights and the real tokenizer, never trained weights,
the backend queue, or a GUI. Success establishes plumbing, not semantic quality.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy", type=Path, required=True)
    opts = parser.parse_args()
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    sys.path.insert(0, str(opts.comfy.resolve()))
    import comfy.cli_args
    comfy.cli_args.args.cpu = True
    comfy.cli_args.args.use_pytorch_cross_attention = True
    import torch
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from moss_capture import attention_weights
    import comfy.ops
    from comfy.ldm.moss_image.model import MOSSImage
    from comfy.text_encoders.moss_image import MOSSImageTokenizer

    torch.set_num_threads(2)
    torch.manual_seed(731)
    tokenizer = MOSSImageTokenizer()
    raw_tokenizer = tokenizer.qwen35_9b.tokenizer
    prompt = "A red cube on the left and a blue sphere on the right."
    rows = tokenizer.tokenize_with_weights(prompt, return_word_ids=True)["qwen35_9b"]
    assert len(rows) == 1
    ids = [item[0] for item in rows[0]]
    decoded = raw_tokenizer.decode(ids)
    assert prompt in decoded
    selected = {}
    for word in ("cube", "sphere"):
        # Match byte-BPE token spans in the actual templated conditioning.
        needle = raw_tokenizer.encode(" " + word, add_special_tokens=False)
        matches = [i for i in range(len(ids) - len(needle) + 1)
                   if ids[i:i + len(needle)] == needle]
        assert len(matches) == 1, (word, matches)
        selected[word] = list(range(matches[0], matches[0] + len(needle)))

    h, w, heads = 3, 5, 2
    image_len, text_len = h * w, len(ids)
    captures, max_error = [], 0.0

    def observe(original, q, k, v, num_heads, **kwargs):
        nonlocal max_error
        options = kwargs.get("transformer_options", {})
        if "block_index" in options:
            assert num_heads == heads
            assert q.shape[1] == image_len + text_len
            batch, length, dim = q.shape
            qh = q.reshape(batch, length, heads, dim // heads).transpose(1, 2).float()
            kh = k.reshape(batch, length, heads, dim // heads).transpose(1, 2).float()
            scale = (dim // heads) ** -0.5
            # Full matrix is ONLY a tiny-fixture reference. The capture path
            # normalizes each image-query chunk over ALL keys, including image
            # keys; softmax over text alone would change the meaning of a map.
            reference = (qh @ kh.transpose(-1, -2) * scale).softmax(-1)
            maps = attention_weights(q, k, heads, image_len, chunk_size=4).transpose(1, 2)
            expected = reference[:, :, :image_len, image_len:].mean(1)
            torch.testing.assert_close(maps, expected, atol=1e-7, rtol=1e-6)
            max_error = max(max_error, (maps - expected).abs().max().item())
            assert torch.isfinite(maps).all() and (maps >= 0).all()
            assert (maps.sum(-1) <= 1.000001).all()
            words = torch.stack([maps[..., indices].sum(-1)
                                 for indices in selected.values()], dim=1)
            words = words.reshape(batch, len(selected), h, w)
            captures.append((options["block_index"], words))
        return original(q, k, v, num_heads, **kwargs)

    results = []
    with torch.inference_mode():
        for fused in (False, True):
            model = MOSSImage(dim=32, ffn_dim=48, num_heads=heads,
                              num_layers=3, text_dim=24, latent_channels=8,
                              fused_qkv=fused, dtype=torch.float32,
                              device="cpu", operations=comfy.ops.manual_cast).eval()
            # Comfy's operations intentionally skip initialization when loading
            # checkpoints. This fixture has no checkpoint: initialize explicitly.
            for name, param in model.named_parameters():
                if param.ndim >= 2:
                    torch.nn.init.normal_(param, std=0.05)
                elif name.endswith("bias"):
                    param.zero_()
                else:
                    param.fill_(1.0)
            x = torch.randn(2, 8, h, w)
            context = torch.randn(2, text_len, 24)
            timestep = torch.tensor([0.7, 0.7])
            captures.clear()
            baseline = model(x.clone(), timestep, context)
            observed = model(x.clone(), timestep, context,
                             transformer_options={"optimized_attention_override": observe})
            assert torch.equal(baseline, observed), "capture changed model output"
            assert [i for i, _ in captures] == [0, 1, 2]
            assert all(tuple(m.shape) == (2, 2, h, w) for _, m in captures)
            assert not torch.equal(captures[0][1][0], captures[0][1][1])
            results.append({"fused_qkv": fused, "captured_blocks": len(captures),
                            "output_bit_identical": True,
                            "map_shape": list(captures[0][1].shape)})
    assert not torch.cuda.is_initialized()
    print(json.dumps({"scope": "random-weight CPU plumbing only; no semantic validation",
                      "prompt": prompt, "conditioning_tokens": text_len,
                      "word_token_indices": selected, "cases": results,
                      "chunked_vs_full_max_error": max_error,
                      "cuda_initialized": False}, indent=2))


if __name__ == "__main__":
    main()
