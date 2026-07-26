"""Identify diffusion models, text encoders, VAEs and LoRAs from file headers alone.

No torch, no safetensors package, no model loading: a safetensors file starts with a
u64le header length followed by that many bytes of JSON describing every tensor, and a
GGUF file starts with a magic + typed key/value block + tensor descriptors.  Both give
us tensor names and shapes for a few hundred KB of reads, which is all the family rules
below need.

The rules mirror ComfyUI's own detection (comfy/model_detection.py, comfy/sd.py) --
that is the authority, and when a Comfy bump moves a signal this is the file to update.
"""

from __future__ import annotations

import json
import os
import struct
import sys

SCHEMA = 3

MODEL_EXTS = (".safetensors", ".sft", ".gguf", ".ckpt", ".pt", ".bin")

# ---------------------------------------------------------------------------
# header readers
# ---------------------------------------------------------------------------


class Header:
    """Normalised view over a safetensors or GGUF header."""

    def __init__(self, tensors: dict, meta: dict, fmt: str):
        self.tensors = tensors  # name -> {"dtype": str, "shape": [int, ...]}
        self.meta = meta
        self.fmt = fmt  # "safetensors" | "gguf"
        self.keys = set(tensors)

    def shape(self, name: str):
        t = self.tensors.get(name)
        return tuple(t["shape"]) if t else None

    def dtype(self, name: str):
        t = self.tensors.get(name)
        return t["dtype"] if t else None

    def dim(self, name: str, idx: int):
        s = self.shape(name)
        if s is None or idx >= len(s):
            return None
        return s[idx]

    def has(self, *names: str) -> bool:
        return all(n in self.keys for n in names)

    def any(self, *names: str) -> bool:
        return any(n in self.keys for n in names)

    def count_prefix(self, prefix: str, sep: str = ".") -> int:
        """Number of distinct integer indices directly under `prefix`."""
        seen = set()
        plen = len(prefix)
        for k in self.keys:
            if not k.startswith(prefix):
                continue
            rest = k[plen:]
            head = rest.split(sep, 1)[0]
            if head.isdigit():
                seen.add(int(head))
        return len(seen)


class BadHeader(Exception):
    pass


def read_safetensors_header(path: str) -> Header:
    with open(path, "rb") as fh:
        raw = fh.read(8)
        if len(raw) < 8:
            raise BadHeader("file shorter than the 8-byte length prefix")
        (n,) = struct.unpack("<Q", raw)
        size = os.path.getsize(path)
        if n <= 0 or n > 100 * 1024 * 1024 or 8 + n > size:
            raise BadHeader(f"implausible header length {n} for a {size}-byte file")
        blob = fh.read(n)
    try:
        doc = json.loads(blob)
    except Exception as exc:  # noqa: BLE001 - any decode failure means "not safetensors"
        raise BadHeader(f"header is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise BadHeader("header JSON is not an object")

    meta = doc.pop("__metadata__", {}) or {}
    tensors = {}
    for name, spec in doc.items():
        if not isinstance(spec, dict) or "shape" not in spec:
            continue
        tensors[name] = {"dtype": spec.get("dtype", "?"), "shape": list(spec["shape"])}
    return Header(tensors, meta if isinstance(meta, dict) else {}, "safetensors")


# GGUF value type ids
_GGUF_U8, _GGUF_I8, _GGUF_U16, _GGUF_I16, _GGUF_U32, _GGUF_I32 = 0, 1, 2, 3, 4, 5
_GGUF_F32, _GGUF_BOOL, _GGUF_STR, _GGUF_ARR, _GGUF_U64, _GGUF_I64, _GGUF_F64 = (
    6, 7, 8, 9, 10, 11, 12,
)
_GGUF_FIXED = {
    _GGUF_U8: ("<B", 1), _GGUF_I8: ("<b", 1),
    _GGUF_U16: ("<H", 2), _GGUF_I16: ("<h", 2),
    _GGUF_U32: ("<I", 4), _GGUF_I32: ("<i", 4),
    _GGUF_F32: ("<f", 4), _GGUF_BOOL: ("<?", 1),
    _GGUF_U64: ("<Q", 8), _GGUF_I64: ("<q", 8), _GGUF_F64: ("<d", 8),
}


class _Cursor:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.buf):
            raise BadHeader("GGUF header truncated (window too small)")
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]

    def string(self) -> str:
        n = self.u64()
        if n > 1 << 24:
            raise BadHeader("implausible GGUF string length")
        return self.take(n).decode("utf-8", "replace")

    def value(self, vtype: int):
        if vtype in _GGUF_FIXED:
            fmt, size = _GGUF_FIXED[vtype]
            return struct.unpack(fmt, self.take(size))[0]
        if vtype == _GGUF_STR:
            return self.string()
        if vtype == _GGUF_ARR:
            etype = self.u32()
            count = self.u64()
            if count > 1 << 22:
                raise BadHeader("implausible GGUF array length")
            # Long homogeneous arrays (tokenizer vocabs) are skipped cheaply.
            if etype in _GGUF_FIXED:
                _, size = _GGUF_FIXED[etype]
                self.take(size * count)
                return f"<{count} x t{etype}>"
            out = []
            for _ in range(count):
                v = self.value(etype)
                if len(out) < 8:
                    out.append(v)
            return out
        raise BadHeader(f"unknown GGUF value type {vtype}")


def read_gguf_header(path: str, window: int = 8 * 1024 * 1024) -> Header:
    with open(path, "rb") as fh:
        buf = fh.read(window)
    if buf[:4] != b"GGUF":
        raise BadHeader("missing GGUF magic")
    cur = _Cursor(buf)
    cur.take(4)
    version = cur.u32()
    if version not in (2, 3):
        raise BadHeader(f"unsupported GGUF version {version}")
    n_tensors = cur.u64()
    n_kv = cur.u64()
    if n_tensors > 1 << 20 or n_kv > 1 << 16:
        raise BadHeader("implausible GGUF counts")

    meta = {}
    for _ in range(n_kv):
        key = cur.string()
        vtype = cur.u32()
        meta[key] = cur.value(vtype)

    tensors = {}
    for _ in range(n_tensors):
        name = cur.string()
        ndim = cur.u32()
        if ndim > 8:
            raise BadHeader("implausible GGUF tensor rank")
        dims = [cur.u64() for _ in range(ndim)]
        ggml_type = cur.u32()
        cur.u64()  # offset
        # GGUF stores dims fastest-varying first; torch order is the reverse.
        tensors[name] = {"dtype": f"ggml{ggml_type}", "shape": list(reversed(dims))}
    return Header(tensors, meta, "gguf")


def read_header(path: str) -> Header:
    if path.endswith(".gguf"):
        return read_gguf_header(path)
    return read_safetensors_header(path)


# ---------------------------------------------------------------------------
# prefix normalisation
# ---------------------------------------------------------------------------

_PREFIXES = ("", "model.diffusion_model.", "diffusion_model.", "net.")

# Signals used only to score which prefix strips cleanest.
_PROBES = (
    "txtfusion.projector.weight",
    "cap_embedder.1.weight",
    "double_blocks.0.img_attn.qkv.weight",
    "distilled_guidance_layer.norms.0.scale",
    "distilled_guidance_layer.layers.0.norms.0.scale",
    "blocks.0.mlp.layer1.weight",
    "llm_adapter.blocks.0.cross_attn.q_proj.weight",
    "img_in.weight",
    "transformer_blocks.0.img_mod.1.weight",
    "layers.0.attention.qkv.weight",
    "input_blocks.0.0.weight",
)


class View:
    """A Header seen through a stripped key prefix."""

    def __init__(self, header: Header, prefix: str):
        self.h = header
        self.prefix = prefix
        if prefix:
            plen = len(prefix)
            self.keys = {k[plen:] for k in header.keys if k.startswith(prefix)}
        else:
            self.keys = set(header.keys)
        self.meta = header.meta

    def shape(self, name):
        return self.h.shape(self.prefix + name)

    def dim(self, name, idx):
        return self.h.dim(self.prefix + name, idx)

    def has(self, *names):
        return all(n in self.keys for n in names)

    def any(self, *names):
        return any(n in self.keys for n in names)

    def count_prefix(self, prefix):
        seen = set()
        for k in self.keys:
            if k.startswith(prefix):
                head = k[len(prefix):].split(".", 1)[0]
                if head.isdigit():
                    seen.add(int(head))
        return len(seen)


def best_view(header: Header) -> View:
    best, best_score = None, -1
    for p in _PREFIXES:
        v = View(header, p)
        if not v.keys:
            continue
        score = sum(1 for probe in _PROBES if probe in v.keys)
        # Prefer a real hit; fall back to the view that kept the most keys.
        score = score * 1000 + min(len(v.keys), 999)
        if score > best_score:
            best, best_score = v, score
    return best if best is not None else View(header, "")


# ---------------------------------------------------------------------------
# diffusion model families
# ---------------------------------------------------------------------------


def _quant_of(header: Header, path: str) -> str:
    if path.endswith(".gguf"):
        ftype = header.meta.get("general.file_type")
        return f"gguf:{ftype}" if ftype is not None else "gguf"
    if any(k.endswith(".comfy_quant") for k in header.keys):
        return "comfy_quant"
    raw = header.meta.get("_quantization_metadata")
    if raw:
        try:
            doc = json.loads(raw) if isinstance(raw, str) else raw
            layers = doc.get("layers") or {}
            for spec in layers.values():
                fmt = spec.get("format")
                if fmt:
                    return str(fmt)
            fmt = doc.get("format")
            if fmt:
                return str(fmt)
        except Exception:  # noqa: BLE001 - metadata is advisory only
            pass
        return "quantized"
    dtypes = {t["dtype"] for t in header.tensors.values()}
    for cand in ("F8_E4M3", "F8_E4M3FN", "F8_E5M2"):
        if cand in dtypes:
            return "float8_e4m3fn"
    if "BF16" in dtypes:
        return "bf16"
    if "F16" in dtypes:
        return "fp16"
    return "fp32" if "F32" in dtypes else "unknown"


def _loader_for(quant: str, path: str) -> str:
    if path.endswith(".gguf"):
        return "UnetLoaderGGUF"
    if quant == "comfy_quant":
        return "OTUNetLoaderW8A8"
    return "UNETLoader"


def detect_diffusion(v: View):
    """Return (family, dims) or (None, {}).  Order matters; first hit wins."""

    # --- Krea 2: the txtfusion projector is unique to it ------------------
    if v.has("txtfusion.projector.weight"):
        return "krea2", {
            "features": v.dim("first.weight", 0) or v.dim("img_in.weight", 0),
            "blocks": v.count_prefix("blocks."),
            "txtdim": v.dim("txtfusion.layerwise_blocks.0.prenorm.scale", 0),
            "txtlayers": v.dim("txtfusion.projector.weight", 1),
        }

    # --- Lumina2 / Z-Image / Z-Image pixel-space (NextDiT) ----------------
    if v.has("cap_embedder.1.weight"):
        dim = v.dim("cap_embedder.1.weight", 0)
        cap = v.dim("cap_embedder.1.weight", 1)
        dims = {"dim": dim, "cap_feat_dim": cap, "layers": v.count_prefix("layers.")}
        if v.any("dec_net.cond_embed.weight") or "__x0__" in v.keys:
            dims["x0"] = "__x0__" in v.keys
            return "zimage_pixel", dims
        if dim and dim >= 3000:
            return "z_image", dims
        return "lumina2", dims

    # --- Chroma: the distilled guidance layer ------------------------------
    if v.any(
        "distilled_guidance_layer.norms.0.scale",
        "distilled_guidance_layer.layers.0.norms.0.scale",
        "distilled_guidance_layer.norms.0.weight",
        "distilled_guidance_layer.in_proj.weight",
    ):
        dims = {
            "double_blocks": v.count_prefix("double_blocks."),
            "single_blocks": v.count_prefix("single_blocks."),
        }
        if v.any("nerf_blocks.0.norm.scale", "nerf_image_embedder.weight"):
            return "chroma_radiance", dims
        return "chroma", dims

    # --- Flux family (Flux 2 Klein distinguished by its modulation split) --
    if v.any("double_blocks.0.img_attn.qkv.weight", "double_blocks.0.img_attn.qkv.scale_weight"):
        dims = {
            "double_blocks": v.count_prefix("double_blocks."),
            "single_blocks": v.count_prefix("single_blocks."),
            "context_in": v.dim("txt_in.weight", 1),
            "hidden": v.dim("txt_in.weight", 0),
        }
        if v.any(
            "double_blocks.0.double_stream_modulation_img.weight",
            "double_stream_modulation_img.weight",
            "double_blocks.0.img_mod.lin.scale_weight",
        ) or (dims["context_in"] or 0) >= 8192:
            return "flux2", dims
        return "flux", dims

    # --- Anima: an LLM adapter with cross attention ------------------------
    if v.any(
        "llm_adapter.blocks.0.cross_attn.q_proj.weight",
        "llm_adapter.blocks.0.cross_attn.q_proj.scale_weight",
    ):
        return "anima", {
            "model_channels": v.dim("x_embedder.proj.1.weight", 0) or v.dim("x_embedder.weight", 0),
            "llm_dim": v.dim("llm_adapter.blocks.0.cross_attn.q_proj.weight", 1),
            "blocks": v.count_prefix("blocks."),
        }

    # --- Qwen-Image (diffusers-style transformer_blocks) -------------------
    if v.has("img_in.weight") and v.count_prefix("transformer_blocks.") > 0:
        return "qwen_image", {
            "in_ch": v.dim("img_in.weight", 1),
            "blocks": v.count_prefix("transformer_blocks."),
        }

    return None, {}


def detect_checkpoint(header: Header):
    """Bundled checkpoints carry the diffusion model, encoders and VAE together."""
    keys = header.keys
    has_unet = any(k.startswith("model.diffusion_model.") for k in keys)
    if not has_unet:
        return None, {}
    has_vae = any(k.startswith(("first_stage_model.", "vae.")) for k in keys)
    has_te = any(k.startswith(("cond_stage_model.", "conditioner.", "text_encoders.")) for k in keys)
    if not (has_vae or has_te):
        return None, {}
    if any(k.startswith("conditioner.embedders.1.") for k in keys):
        return "sdxl_ckpt", {"tensors": len(keys)}
    inner, dims = detect_diffusion(View(header, "model.diffusion_model."))
    if inner == "lumina2":
        return "lumina2_ckpt", dims
    if inner:
        return f"{inner}_ckpt", dims
    return "checkpoint", {"tensors": len(keys)}


# ---------------------------------------------------------------------------
# text encoders  (mirrors comfy/sd.py detect_te_model)
# ---------------------------------------------------------------------------


def detect_text_encoder(header: Header):
    h = header
    if h.dim("encoder.block.23.layer.1.DenseReluDense.wi_1.weight", 0) == 10240:
        return "T5_XXL", {"hidden": h.dim("shared.weight", 1)}
    if h.any("encoder.block.0.layer.0.SelfAttention.k.weight"):
        return "T5", {"hidden": h.dim("shared.weight", 1)}

    visual = any(k.startswith(("model.visual.", "visual.")) for k in h.keys)
    hidden = (
        h.dim("model.layers.0.post_attention_layernorm.weight", 0)
        or h.dim("layers.0.post_attention_layernorm.weight", 0)
    )
    layers = h.count_prefix("model.layers.") or h.count_prefix("layers.")
    qnorm = h.any("model.layers.0.self_attn.q_norm.weight", "layers.0.self_attn.q_norm.weight")
    kbias = h.dim("model.layers.0.self_attn.k_proj.bias", 0)

    if visual and h.any(
        "model.visual.deepstack_merger_list.0.norm.weight",
        "visual.deepstack_merger_list.0.norm.weight",
    ):
        # Qwen3-VL: sized by its own hidden dim.
        if hidden == 2560:
            return "QWEN3VL_4B", {"hidden": hidden, "layers": layers}
        return "QWEN3VL", {"hidden": hidden, "layers": layers}
    if visual and kbias == 512:
        return "QWEN25_7B", {"hidden": hidden, "layers": layers}
    if hidden and qnorm:
        return {2560: "QWEN3_4B", 4096: "QWEN3_8B", 1024: "QWEN3_06B"}.get(
            hidden, f"QWEN3_{hidden}"
        ), {"hidden": hidden, "layers": layers}
    if hidden:
        return f"LLM_{hidden}", {"hidden": hidden, "layers": layers}
    if h.any("text_model.encoder.layers.0.self_attn.k_proj.weight"):
        width = h.dim("text_model.embeddings.token_embedding.weight", 1)
        return ("CLIP_G" if width == 1280 else "CLIP_L"), {"hidden": width}
    return None, {}


# ---------------------------------------------------------------------------
# VAEs
# ---------------------------------------------------------------------------

# qwen_image_vae and wan21-vae are structurally identical, so structure alone
# cannot separate them; the hash decides, then the filename, then the user.
VAE_SHA_HINTS = {}


def detect_vae(header: Header):
    keys = header.keys
    if "pixel_space_vae" in keys:
        return "pixel_space", {"latent_channels": 3, "downscale": 1}
    if not any(k.startswith(("encoder.", "decoder.")) or k in ("conv1.weight",) for k in keys):
        return None, {}
    n = len(keys)
    if header.any("conv1.weight", "conv2.weight") or n == 194:
        return "wan21", {"latent_channels": 16, "tensors": n}
    if header.any("bn.running_mean") or header.any("quant_conv.weight") and n > 245:
        return "flux2", {"latent_channels": 128, "tensors": n}
    cin = header.shape("decoder.conv_in.weight")
    if cin and len(cin) == 4:
        ch = cin[1]
        attn = header.any("decoder.mid.attn_1.k.weight", "decoder.mid.attn_1.to_k.weight")
        return "flux_ae" if ch == 16 else "sd_ae", {
            "latent_channels": ch,
            "tensors": n,
            "mid_attn": attn,
        }
    return "vae", {"tensors": n}


# ---------------------------------------------------------------------------
# LoRAs
# ---------------------------------------------------------------------------

_ADAPTER_SUFFIXES = (
    ".lora_A.weight", ".lora_B.weight",
    ".lora_down.weight", ".lora_up.weight",
    ".lora_A.default.weight", ".lora_B.default.weight",
    ".lokr_w1", ".lokr_w2", ".lokr_w1_a", ".lokr_w1_b", ".lokr_w2_a", ".lokr_w2_b",
    ".hada_w1_a", ".hada_w1_b", ".hada_w2_a", ".hada_w2_b",
    ".diff", ".diff_b", ".alpha", ".dora_scale",
)

_WRAPPER_PREFIXES = (
    "diffusion_model.", "transformer.", "model.diffusion_model.", "net.",
    "lora_unet_", "lora_te_", "lora_te1_", "lora_te2_", "base_model.model.",
)


def _strip_adapter(key: str):
    for suf in _ADAPTER_SUFFIXES:
        if key.endswith(suf):
            return key[: -len(suf)], suf
    return None, None


def lora_targets(header: Header):
    """Recover the base-model key namespace a LoRA patches.

    Also returns how many keys carried an adapter suffix, which is what tells a
    LoRA apart from a base model: adapters use three tensors per patched module
    (alpha + down + up), so counting distinct targets against total keys is not a
    usable ratio -- coverage is.
    """
    targets = set()
    kohya = False
    touches_te = False
    adapter_keys = 0
    for k in header.keys:
        base, _suf = _strip_adapter(k)
        if base is None:
            continue
        adapter_keys += 1
        if base.startswith(("lora_te", "text_encoders.", "cond_stage_model.")):
            touches_te = True
        for pre in _WRAPPER_PREFIXES:
            if base.startswith(pre):
                if pre.startswith("lora_"):
                    kohya = True
                base = base[len(pre):]
                break
        targets.add(base)
    return targets, kohya, touches_te, adapter_keys


def _dedot(name: str) -> str:
    return name.replace(".", "_")


def lora_match_score(targets, kohya: bool, base_keys, aliases: dict | None = None):
    """Fraction of LoRA target keys that resolve to a real base-model module.

    Base weights are `<module>.weight`; kohya writes `<module>` with dots replaced
    by underscores, so for that flavour we compare against a de-dotted index of the
    base's module names (the same reconstruction comfy/lora.py performs).
    """
    if not targets:
        return 0.0, 0, set()

    modules = set()
    for k in base_keys:
        # fp8 checkpoints carry a companion `.weight_scale` per weight
        for suf in (".weight_scale", ".scale_weight", ".weight", ".bias", ".scale"):
            if k.endswith(suf):
                modules.add(k[: -len(suf)])
                break
        else:
            modules.add(k)

    lookup = {_dedot(m): m for m in modules} if kohya else None

    hits, missed = 0, set()
    for t in targets:
        cand = t
        if aliases:
            for src, dst in aliases.items():
                if src in cand:
                    cand = cand.replace(src, dst)
        if kohya:
            if _dedot(cand) in lookup:
                hits += 1
                continue
        if cand in modules or f"{cand}.weight" in base_keys or cand in base_keys:
            hits += 1
            continue
        missed.add(t)
    return hits / len(targets), hits, missed


def detect_lora(header: Header):
    targets, kohya, touches_te, _cov = lora_targets(header)
    if not targets:
        return None, {}
    meta = header.meta or {}
    declared = None
    for key in ("modelspec.architecture", "ss_base_model_version", "ss_network_module"):
        val = meta.get(key)
        if val:
            declared = str(val)
            break
    sample = sorted(targets)[:4]
    return "lora", {
        "targets": len(targets),
        "kohya": kohya,
        "patches_clip": touches_te,
        "declared": declared,
        "sample_targets": sample,
        "rank": _lora_rank(header),
    }


def _lora_rank(header: Header):
    for k, spec in header.tensors.items():
        if k.endswith((".lora_down.weight", ".lora_A.weight")):
            shape = spec["shape"]
            if shape:
                return shape[0]
    return None


# ---------------------------------------------------------------------------
# top-level classification
# ---------------------------------------------------------------------------

ROLE_BY_DIR = {
    "diffusion_models": "diffusion",
    "unet": "diffusion",
    "checkpoints": "checkpoint",
    "text_encoders": "text_encoder",
    "clip": "text_encoder",
    "vae": "vae",
    "loras": "lora",
}

# Directories holding things that are not diffusion assets (captioners, etc).
IGNORED_DIRS = frozenset({"LLavacheckpoints", "clip_vision", "configs"})


def classify(path: str, role_hint: str | None = None) -> dict:
    """Full identification of one model file.  Never raises."""
    out = {"path": path, "role": role_hint, "family": None, "error": None}
    try:
        header = read_header(path)
    except BadHeader as exc:
        out["error"] = str(exc)
        out["family"] = "unreadable"
        return out
    except OSError as exc:
        out["error"] = f"{exc}"
        out["family"] = "unreadable"
        return out

    out["tensors"] = len(header.tensors)
    out["format"] = header.fmt

    # A LoRA is recognised by its adapter suffixes regardless of where it lives.
    targets, kohya, touches_te, adapter_keys = lora_targets(header)
    looks_lora = bool(targets) and adapter_keys >= 0.9 * len(header.keys)

    if looks_lora and role_hint in (None, "lora"):
        fam, dims = detect_lora(header)
        out.update(role="lora", family="lora", dims=dims)
        return out

    if role_hint == "text_encoder":
        fam, dims = detect_text_encoder(header)
        out.update(role="text_encoder", family=fam or "unknown", dims=dims)
        return out

    if role_hint == "vae":
        fam, dims = detect_vae(header)
        out.update(role="vae", family=fam or "unknown", dims=dims)
        return out

    ckpt_fam, ckpt_dims = detect_checkpoint(header)
    if ckpt_fam:
        out.update(
            role="checkpoint",
            family=ckpt_fam,
            dims=ckpt_dims,
            loader="CheckpointLoaderSimple",
            quant=_quant_of(header, path),
        )
        return out

    view = best_view(header)
    fam, dims = detect_diffusion(view)
    if fam:
        quant = _quant_of(header, path)
        out.update(
            role="diffusion",
            family=fam,
            dims=dims,
            quant=quant,
            loader=_loader_for(quant, path),
            key_prefix=view.prefix,
        )
        return out

    # Fall through: maybe it is an encoder or VAE filed in the wrong directory.
    fam, dims = detect_text_encoder(header)
    if fam:
        out.update(role="text_encoder", family=fam, dims=dims)
        return out
    fam, dims = detect_vae(header)
    if fam:
        out.update(role="vae", family=fam, dims=dims)
        return out

    out["family"] = "unknown"
    out["sample_keys"] = sorted(header.keys)[:6]
    return out


# ---------------------------------------------------------------------------
# scanning + cache
# ---------------------------------------------------------------------------


def cache_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "painter", "fingerprints.json")


def load_cache() -> dict:
    try:
        with open(cache_path(), "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        if doc.get("schema") == SCHEMA:
            return doc.get("entries", {})
    except (OSError, ValueError):
        pass
    return {}


def save_cache(entries: dict) -> None:
    p = cache_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"schema": SCHEMA, "entries": entries}, fh, indent=1, sort_keys=True)
    os.replace(tmp, p)


def iter_model_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        rel = os.path.relpath(dirpath, root)
        top = rel.split(os.sep)[0] if rel != "." else ""
        if top in IGNORED_DIRS:
            dirnames[:] = []
            continue
        hint = ROLE_BY_DIR.get(top)
        for name in sorted(filenames):
            if not name.endswith(MODEL_EXTS):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            if st.st_size == 0:
                continue
            yield full, hint, st


def scan(roots, use_cache: bool = True, progress=None) -> list:
    entries = load_cache() if use_cache else {}
    results, dirty = [], False
    for root in roots:
        for full, hint, st in iter_model_files(root):
            key = os.path.realpath(full)
            cached = entries.get(key)
            if (
                use_cache
                and cached
                and cached.get("size") == st.st_size
                and cached.get("mtime_ns") == st.st_mtime_ns
            ):
                res = dict(cached["result"])
                res["path"] = full
            else:
                res = classify(full, hint)
                entries[key] = {
                    "size": st.st_size,
                    "mtime_ns": st.st_mtime_ns,
                    "result": res,
                }
                dirty = True
            res["size"] = st.st_size
            results.append(res)
            if progress:
                progress(res)
    if use_cache and dirty:
        try:
            save_cache(entries)
        except OSError:
            pass
    return results


def _main(argv):
    import argparse

    ap = argparse.ArgumentParser(description="Identify models from their headers.")
    ap.add_argument("--scan", action="append", default=[], metavar="ROOT")
    ap.add_argument("--file", action="append", default=[], metavar="PATH")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)

    roots = args.scan or ([] if args.file else ["/home/lam/models"])
    results = scan(roots, use_cache=not args.no_cache) if roots else []
    for f in args.file:
        results.append(classify(f, ROLE_BY_DIR.get(os.path.basename(os.path.dirname(f)))))

    if args.json:
        slim = [
            {
                "name": os.path.basename(r["path"]),
                "role": r.get("role"),
                "family": r.get("family"),
                "loader": r.get("loader"),
                "quant": r.get("quant"),
                "dims": r.get("dims"),
            }
            for r in sorted(results, key=lambda r: (r.get("role") or "", os.path.basename(r["path"])))
        ]
        json.dump(slim, sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    by_role = {}
    for r in results:
        by_role.setdefault(r.get("role") or "?", []).append(r)
    for role in sorted(by_role):
        print(f"\n=== {role} ({len(by_role[role])}) ===")
        for r in sorted(by_role[role], key=lambda x: os.path.basename(x["path"])):
            name = os.path.basename(r["path"])
            extra = []
            if r.get("quant"):
                extra.append(r["quant"])
            if r.get("loader"):
                extra.append(r["loader"])
            if r.get("error"):
                extra.append(f"ERROR {r['error']}")
            dims = r.get("dims") or {}
            if dims:
                extra.append(" ".join(f"{k}={v}" for k, v in dims.items() if v is not None))
            print(f"  {name:<58} {r.get('family')}" + (f"   [{'; '.join(extra)}]" if extra else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
