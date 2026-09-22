"""Qwen 2.1 signed attention-value weighting, using native attention hooks."""
from functools import partial
import copy
import math
import numbers

import torch
import comfy.conds
import comfy.model_base
import comfy.patcher_extension
import nodes
from comfy.text_encoders.qwen_image21 import QwenImage21TEModel

KEY = "painter_qwen21_weights"


def weighted_tokenizer(tokenizer):
    # Native Qwen explicitly disables Comfy's weight parser. Override only
    # the cloned leaf tokenizer, retaining its native template/image handling.
    clone = copy.copy(tokenizer)
    leaf = copy.copy(getattr(clone, clone.clip))
    original = leaf.tokenize_with_weights
    def tokenize(*args, **kwargs):
        kwargs["disable_weights"] = False
        return original(*args, **kwargs)
    leaf.tokenize_with_weights = tokenize
    setattr(clone, clone.clip, leaf)
    return clone


def text_weights(pairs, image_spans, keep_vision):
    """Mirror the native encoder's image expansion and system/vision trimming."""
    weights, starts = [], []
    spans = iter(image_spans)
    for token, weight, *_ in pairs:
        if isinstance(token, numbers.Integral) and token == 151644:
            starts.append(len(weights))
        if isinstance(token, dict) and token.get("type") == "image":
            _, size = next(spans)
            weights.extend([1.0] * size)
        else:
            weights.append(float(weight))
    keep = [True] * len(weights)
    keep[:starts[1] if len(starts) > 1 else 0] = [False] * (starts[1] if len(starts) > 1 else 0)
    if not keep_vision:
        for start, size in image_spans:
            keep[start:start + size] = [False] * size
    return [w for w, yes in zip(weights, keep) if yes]


def encode_weights(te, original, tokens):
    sections = tokens["qwen3vl_8b"]
    if len(sections) != 1:
        raise ValueError("Qwen 2.1 NegPip requires one native token sequence")
    # Keep the language model's features intact. Signed weights act on V in
    # every DiT block, rather than becoming negative language-model features.
    plain = dict(tokens)
    plain["qwen3vl_8b"] = [[(t[0], 1.0, *t[2:]) for t in sections[0]]]
    out, pooled, extra = original(plain)
    weights = text_weights(sections[0], getattr(te, te.clip).image_spans,
                           tokens.get("keep_vision", False))
    if len(weights) != out.shape[1]:
        raise ValueError("Qwen 2.1 NegPip token layout differs from native conditioning")
    weights = out.new_tensor(weights).reshape(1, -1, 1)
    return out, pooled, {**extra, KEY: weights}


def extra_conds(original, **kwargs):
    out = original(**kwargs)
    if KEY in kwargs:
        out[KEY] = comfy.conds.CONDRegular(kwargs[KEY])
    return out


def sequence_weights(weights, refs, slots, target_tokens):
    """Insert neutral reference/target weights at native image-slot positions."""
    slots = (list(slots) + [weights.shape[1]] * len(refs))[:len(refs)]
    bounds = [0] + slots + [weights.shape[1]]
    parts = []
    for i, (start, end) in enumerate(zip(bounds[:-1], bounds[1:])):
        parts.append(weights[:, start:end])
        count = refs[i].shape[-2] * refs[i].shape[-1] if i < len(refs) else target_tokens
        parts.append(weights.new_ones((weights.shape[0], count, 1)))
    return torch.cat(parts, dim=1)


def attention_values(q, k, v, pe=None, attn_mask=None, extra_options=None):
    weights = extra_options[KEY].to(v).unsqueeze(1)
    if weights.shape[2] != v.shape[2]:
        raise ValueError("Qwen 2.1 NegPip attention sequence does not match its weights")
    return {"q": q, "k": k, "v": v * weights, "pe": pe}


def diffusion_wrapper(executor, x, timestep, context, ref_latents=None,
                      image_slots=None, transformer_options=None, **kwargs):
    weights = kwargs.pop(KEY, None)
    options = dict(transformer_options or {})
    if weights is not None:
        options[KEY] = sequence_weights(weights, list(ref_latents or []),
                                       list(image_slots or []), x.shape[-2] * x.shape[-1])
        patches = dict(options.get("patches", {}))
        patches["attn1_patch"] = [*patches.get("attn1_patch", []), attention_values]
        options["patches"] = patches
        # Native Qwen disables prefix caching whenever an attention hook is
        # present, so signed values cannot be reused under different weights.
    return executor(x, timestep, context, ref_latents, image_slots, options, **kwargs)


class PainterQwen21NegPip:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "clip": ("CLIP",)}}

    RETURN_TYPES = ("MODEL", "CLIP")
    FUNCTION = "patch"
    CATEGORY = "conditioning"

    def patch(self, model, clip):
        if not isinstance(model.model, comfy.model_base.QwenImage21):
            raise ValueError("PainterQwen21NegPip requires Qwen-Image 2.1")
        te = clip.patcher.model
        if not isinstance(te, QwenImage21TEModel):
            raise ValueError("PainterQwen21NegPip requires the Qwen 2.1 encoder")
        m, c = model.clone(), clip.clone()
        c.tokenizer = weighted_tokenizer(clip.tokenizer)
        c.patcher.add_object_patch("encode_token_weights",
                                  partial(encode_weights, te, te.encode_token_weights))
        m.add_object_patch("extra_conds", partial(extra_conds, m.model.extra_conds))
        m.add_wrapper_with_key(comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL,
                               KEY, diffusion_wrapper)
        return m, c


class PainterQwen21ModelSampling:
    @classmethod
    def INPUT_TYPES(cls):
        return nodes.NODE_CLASS_MAPPINGS["ModelSamplingSD3Advanced"].INPUT_TYPES()

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "patch"
    CATEGORY = "advanced/model"

    def patch(self, model, **params):
        if not isinstance(model.model, comfy.model_base.QwenImage21):
            raise ValueError("PainterQwen21ModelSampling requires Qwen-Image 2.1")
        node = nodes.NODE_CLASS_MAPPINGS["ModelSamplingSD3Advanced"]()
        m, = node.patch(model, **params)
        sampling = m.get_model_object("model_sampling")
        # Flux stores log(alpha); SD3Advanced's outside-window baseline needs
        # alpha itself. Convert it without mutating the model's shared config.
        sampling._default_shift = math.exp(model.model.model_config.sampling_settings["shift"])
        sampling.set_parameters(**params, timesteps=10000)
        return (m,)


NODE_CLASS_MAPPINGS = {"PainterQwen21NegPip": PainterQwen21NegPip,
                       "PainterQwen21ModelSampling": PainterQwen21ModelSampling}
