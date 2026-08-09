"""Turn a folder of model files into a set of ready-to-run choices.

The user picks a diffusion model; everything else -- text encoder, VAE, graph,
sampler defaults, which LoRAs are even applicable -- is derived here.  Family
descriptions are data (`families/*.json`), so a new architecture is a new file,
not new code.  Anything the fingerprinter cannot place stays visible as
`unknown` and can be assigned by hand; those assignments are remembered.
"""

from __future__ import annotations

import json
import os

import fingerprint as fp
import graph as G

HERE = os.path.dirname(os.path.abspath(__file__))
FAMILY_DIR = os.path.join(HERE, "families")
MODEL_ROOT = os.environ.get("PAINTER_MODELS", "/home/lam/models")

# THE FOUR THINGS HE REACHES FOR, as one button each above the model list.
# A mode is a SHORTCUT to a model, not a new kind of model: picking one selects
# the file named here and greys the list out, and turning it off hands the list
# back. `edit` additionally asks its family for the edit pipeline (see
# `build()`), which is why it is the only one that can be unavailable for a
# reason other than a missing file.
#
# `prefer` is tried in order, first as an exact filename and then as a
# substring, so a renamed or re-quantised file still lands somewhere sensible
# instead of the mode going dark; the last resort is the first model of the
# family. Which file each mode means is HIS choice (krea 2 raw fp8 for `real`,
# 2026-08-06), not something to be re-derived from what looks newest.
MODES = [
    {"id": "anime", "label": "anime", "family": "anima",
     "prefer": ["anima-base-v1.0.safetensors", "base"],
     "tip": "Anima - the anime base model"},
    {"id": "real", "label": "real", "family": "krea2",
     "prefer": ["krea2_raw_fp8_scaled.safetensors", "raw_fp8", "raw"],
     "tip": "Flux Krea 2, raw"},
    {"id": "edit", "label": "edit", "family": "flux2", "needs": "edit",
     "prefer": ["flux-2-klein-9b-fp8.safetensors", "klein"],
     "tip": "Edit a dropped image - Flux 2 Klein"},
    {"id": "video", "label": "video", "family": "minimax_h3",
     "prefer": ["minimax_h3_fl2va_pruned_int8_convrot.safetensors", "minimax"],
     "tip": "MiniMax H3 - picture and sound"},
]


def mode_spec(mode_id: str):
    for m in MODES:
        if m["id"] == mode_id:
            return m
    return None


SUB = {
    "diffusion": ("diffusion_models", "unet"),
    "checkpoint": ("checkpoints",),
    "text_encoder": ("text_encoders", "clip"),
    "vae": ("vae",),
    "lora": ("loras",),
}


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "painter")


def overrides_path() -> str:
    return os.path.join(state_dir(), "overrides.json")


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Overrides:
    def __init__(self, path=None):
        self.path = path or overrides_path()
        self.doc = {"files": {}, "families": {}, "lora_force": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            for k in self.doc:
                if isinstance(loaded.get(k), dict):
                    self.doc[k] = loaded[k]
        except (OSError, ValueError):
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.doc, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    def for_file(self, path: str) -> dict:
        return self.doc["files"].get(os.path.realpath(path), {})

    def set_file(self, path: str, **kw):
        entry = self.doc["files"].setdefault(os.path.realpath(path), {})
        entry.update({k: v for k, v in kw.items() if v is not None})
        self.save()

    def clear_file(self, path: str):
        self.doc["files"].pop(os.path.realpath(path), None)
        self.save()

    def forced_families(self, lora_path: str):
        return self.doc["lora_force"].get(os.path.realpath(lora_path), [])

    def force_lora(self, lora_path: str, families):
        self.doc["lora_force"][os.path.realpath(lora_path)] = list(families)
        self.save()


def load_families(overrides: Overrides | None = None) -> dict:
    fams = {}
    for name in sorted(os.listdir(FAMILY_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(FAMILY_DIR, name), "r", encoding="utf-8") as fh:
            doc = json.load(fh)
        fams[doc["id"]] = doc
    if overrides:
        for fid, patch in (overrides.doc.get("families") or {}).items():
            if fid in fams:
                fams[fid] = _deep_merge(fams[fid], patch)
    return fams


# ---------------------------------------------------------------------------


class Entry:
    """One model file plus everything known about it."""

    __slots__ = ("path", "name", "role", "family", "dims", "quant", "loader",
                 "size", "error", "keys", "targets", "kohya", "patches_clip",
                 "declared", "overridden")

    def __init__(self, res: dict, overridden=False):
        self.path = res["path"]
        self.name = os.path.basename(self.path)
        self.role = res.get("role")
        self.family = res.get("family")
        self.dims = res.get("dims") or {}
        self.quant = res.get("quant")
        self.loader = res.get("loader")
        self.size = res.get("size", 0)
        self.error = res.get("error")
        self.overridden = overridden
        self.keys = None
        self.targets = None
        self.kohya = False
        self.patches_clip = False
        self.declared = None

    def __repr__(self):
        return f"<Entry {self.name} {self.role}/{self.family}>"


class Registry:
    def __init__(self, root: str = MODEL_ROOT, overrides: Overrides | None = None,
                 use_cache: bool = True):
        self.root = root
        self.overrides = overrides or Overrides()
        self.families = load_families(self.overrides)
        self.entries = []
        self.by_role = {}
        self.scan(use_cache=use_cache)

    # -- discovery ---------------------------------------------------------

    def scan(self, use_cache: bool = True):
        results = fp.scan([self.root], use_cache=use_cache)
        self.entries = []
        for res in results:
            ov = self.overrides.for_file(res["path"])
            if ov.get("family"):
                res = dict(res, family=ov["family"], role=ov.get("role", res.get("role")))
            self.entries.append(Entry(res, overridden=bool(ov.get("family"))))
        self.by_role = {}
        for e in self.entries:
            self.by_role.setdefault(e.role, []).append(e)
        for lst in self.by_role.values():
            lst.sort(key=lambda e: e.name.lower())

    def base_models(self):
        return self.by_role.get("diffusion", []) + self.by_role.get("checkpoint", [])

    def encoders(self):
        return self.by_role.get("text_encoder", [])

    def vaes(self):
        return self.by_role.get("vae", [])

    def loras(self):
        return self.by_role.get("lora", [])

    def find(self, name: str):
        for e in self.entries:
            if e.name == name:
                return e
        return None

    # -- modes -------------------------------------------------------------

    def mode_model(self, mode_id: str):
        """The base model a mode button selects, or None if it is not here.

        Exact filename first, then substring, then any model of the family —
        the mode is a shortcut and a shortcut that goes dark because a file was
        re-quantised is worse than one that lands on the sibling next to it.
        """
        spec = mode_spec(mode_id)
        if not spec:
            return None
        cands = [e for e in self.base_models() if e.family == spec["family"]]
        if not cands:
            return None
        if spec.get("needs") == "edit":
            cands = [e for e in cands if (self.family_of(e) or {}).get("edit")]
            if not cands:
                return None
        for want in spec.get("prefer") or []:
            for e in cands:
                if e.name == want:
                    return e
        for want in spec.get("prefer") or []:
            for e in cands:
                if want.lower() in e.name.lower():
                    return e
        return cands[0]

    def mode_of(self, entry: Entry) -> str:
        """Which mode this model IS, so a hand-picked one can light its button."""
        if entry is None:
            return ""
        for spec in MODES:
            if entry.family == spec["family"] and self.mode_model(spec["id"]) is entry:
                return spec["id"]
        return ""

    # -- pairing -----------------------------------------------------------

    def family_of(self, entry: Entry):
        return self.families.get(entry.family)

    def pair(self, entry: Entry) -> dict:
        """Resolve a base model into a complete, runnable configuration."""
        fam = self.family_of(entry)
        ov = self.overrides.for_file(entry.path)
        out = {
            "model": entry,
            "family": fam,
            "family_id": entry.family,
            "encoder": None,
            "vae": None,
            "vae_audio": None,
            "problems": [],
            "notes": [],
        }
        if fam is None:
            out["problems"].append(
                f"no family definition for {entry.family!r} - assign one to use this model"
            )
            return out

        if fam.get("loader_shape") == "checkpoint":
            out["notes"].append("bundled checkpoint: encoder and VAE come from the file")
        else:
            out["encoder"] = self._pick_encoder(fam, entry, ov)
            out["vae"] = self._pick_vae(fam.get("vae"), ov)
            if out["encoder"] is None:
                want = (fam.get("text_encoder") or {}).get("te_model")
                out["problems"].append(f"no text encoder of type {want} found")
            if out["vae"] is None:
                want = (fam.get("vae") or {}).get("arch")
                out["problems"].append(f"no {want} VAE found")
            # A video family decodes two latents: pictures and sound. The audio
            # VAE is a second, separate file, and missing it is a problem here
            # rather than a submit-time node error.
            if fam.get("vae_audio"):
                out["vae_audio"] = self._pick_vae(fam.get("vae_audio"), ov, key="vae_audio")
                if out["vae_audio"] is None:
                    out["problems"].append("no audio VAE found")
        return out

    def _pick_encoder(self, fam, entry, ov):
        if ov.get("encoder"):
            e = self.find(ov["encoder"])
            if e:
                return e
        spec = fam.get("text_encoder") or {}
        want = spec.get("te_model")
        cands = [e for e in self.encoders() if e.family == want]
        if not cands:
            return None
        # When several encoders share a type, prefer one whose hidden size the
        # base model's own dimensions confirm.
        hidden = spec.get("hidden")
        exact = [e for e in cands if e.dims.get("hidden") == hidden]
        return (exact or cands)[0]

    def _pick_vae(self, spec, ov, key="vae"):
        if ov.get(key):
            v = self.find(ov[key])
            if v:
                return v
        spec = spec or {}
        for name in spec.get("prefer") or []:
            v = self.find(name)
            if v:
                return v
        arch = spec.get("arch")
        cands = [v for v in self.vaes() if v.family == arch]
        return cands[0] if cands else None

    # -- LoRA compatibility -------------------------------------------------

    def _base_keys(self, entry: Entry):
        if entry.keys is None:
            try:
                header = fp.read_header(entry.path)
                prefix = "model.diffusion_model." if entry.role == "checkpoint" else None
                view = fp.View(header, prefix) if prefix else fp.best_view(header)
                entry.keys = view.keys
            except Exception:  # noqa: BLE001 - an unreadable base just matches nothing
                entry.keys = set()
        return entry.keys

    def _lora_targets(self, lora: Entry):
        if lora.targets is None:
            try:
                header = fp.read_header(lora.path)
                t, kohya, te, _ = fp.lora_targets(header)
                lora.targets, lora.kohya, lora.patches_clip = t, kohya, te
                lora.declared = (lora.dims or {}).get("declared")
            except Exception:  # noqa: BLE001
                lora.targets, lora.kohya = set(), False
        return lora.targets

    def lora_compat(self, lora: Entry, base: Entry, threshold: float = 0.8):
        """How well a LoRA fits a base model, and why."""
        if base.family in self.overrides.forced_families(lora.path):
            return {"ok": True, "score": 1.0, "reason": "forced by user"}
        targets = self._lora_targets(lora)
        if not targets:
            return {"ok": False, "score": 0.0, "reason": "no adapter tensors found"}
        fam = self.family_of(base) or {}
        aliases = ((fam.get("lora") or {}).get("aliases")) or {}
        keys = self._base_keys(base)
        if not keys:
            return {"ok": False, "score": 0.0, "reason": "base model unreadable"}
        score, hits, missed = fp.lora_match_score(targets, lora.kohya, keys, aliases)
        if score >= threshold:
            return {"ok": True, "score": score,
                    "reason": f"{hits}/{len(targets)} target modules matched"}
        sample = sorted(missed)[:1]
        detail = f" (e.g. {sample[0]})" if sample else ""
        return {
            "ok": False, "score": score,
            "reason": f"only {score * 100:.0f}% of its {len(targets)} targets exist in this model{detail}",
        }

    def compatible_loras(self, base: Entry, threshold: float = 0.8):
        ok, no = [], []
        for lora in self.loras():
            verdict = self.lora_compat(lora, base, threshold)
            (ok if verdict["ok"] else no).append((lora, verdict))
        ok.sort(key=lambda p: p[0].name.lower())
        no.sort(key=lambda p: -p[1]["score"])
        return ok, no

    # -- building a job -----------------------------------------------------

    def defaults_for(self, entry: Entry) -> dict:
        fam = self.family_of(entry) or {}
        d = dict(fam.get("defaults") or {})
        for tag, patch in (fam.get("variants") or {}).items():
            if tag in entry.name.lower():
                d.update(patch)
        return d

    def build(self, entry: Entry, params: dict, object_info: dict | None = None) -> dict:
        """Produce the ComfyUI prompt for one generation.

        `params` carries what the UI controls: prompts, seed, steps, cfg, sampler,
        scheduler, denoise, width, height, batch, loras, and toggle states.
        """
        pairing = self.pair(entry)
        fam = pairing["family"]
        if fam is None:
            raise G.GraphError(pairing["problems"][0])
        if pairing["problems"]:
            raise G.GraphError("; ".join(pairing["problems"]))

        # EDITING IS A DIFFERENT PIPELINE, not a flag on the image one: no empty
        # latent to sample from, no negative prompt to encode, and the size comes
        # out of the dropped image. A family says whether it can do it at all
        # (`edit` block, flux2 only so far) and which template that takes.
        espec = fam.get("edit") or {}
        edit = bool((params or {}).get("edit")) and bool(espec)
        if (params or {}).get("edit") and not espec:
            raise G.GraphError(f"{fam.get('label', fam['id'])} cannot edit an image")

        g = G.Graph(G.load_template(
            espec["graph"] if edit else fam.get("graph", "universal.json")))
        defaults = self.defaults_for(entry)
        if edit:
            defaults = {**defaults, **(espec.get("defaults") or {})}
        p = {**defaults, **(params or {})}

        # --- loader ---------------------------------------------------------
        if fam.get("loader_shape") == "checkpoint":
            g.set_input("loader", "ckpt_name", entry.name)
        else:
            # A family may pin the loader class. MiniMax H3 ships comfy-quantized,
            # so the fingerprinter reaches for OTUNetLoaderW8A8, but the workflow
            # that produced the first outputs loads it on the plain UNETLoader.
            # What is known to run wins over what is inferred.
            loader = fam.get("loader_class") or entry.loader or "UNETLoader"
            if loader == "UnetLoaderGGUF":
                g.set_class("loader", "UnetLoaderGGUF", drop=("weight_dtype",))
                g.set_input("loader", "unet_name", entry.name)
            elif loader == "OTUNetLoaderW8A8":
                int8 = dict(fam.get("int8") or {})
                int8.setdefault("model_type", fam["id"])
                int8.setdefault("on_the_fly_quantization", False)
                int8.setdefault("enable_convrot", True)
                int8.setdefault("lora_mode", "None")
                g.set_class("loader", "OTUNetLoaderW8A8", inputs=int8)
                g.set_input("loader", "unet_name", entry.name)
                g.set_input("loader", "weight_dtype", "default")
            else:
                g.set_input("loader", "unet_name", entry.name)
                g.set_input("loader", "weight_dtype", p.get("weight_dtype", "default"))

            te = fam.get("text_encoder") or {}
            g.set_input("clip", "clip_name", pairing["encoder"].name)
            g.set_input("clip", "type", te.get("clip_type", "stable_diffusion"))
            g.set_input("vae", "vae_name", pairing["vae"].name)
            if pairing.get("vae_audio") is not None:
                g.set_input("vae_audio", "vae_name", pairing["vae_audio"].name)

        if edit:
            return self._build_edit(entry, fam, g, p, pairing, object_info)

        if fam.get("kind") == "video":
            return self._build_video(entry, fam, g, p, pairing, object_info)

        # --- optional nodes --------------------------------------------------
        toggles = {**(fam.get("toggles") or {}), **(p.get("toggles") or {})}
        if toggles.get("model_sampling", False):
            ms = {**(fam.get("model_sampling") or {}), **(p.get("model_sampling") or {})}
            g.set_inputs("model_sampling", ms)
        else:
            g.remove("model_sampling")
        if not toggles.get("negpip", False):
            g.remove("negpip")

        # --- LoRA chain ------------------------------------------------------
        loras = p.get("loras") or []
        if loras:
            loader_id = g.id_of("loader")
            model_src = [loader_id, 0]
            clip_src = None
            if fam.get("loader_shape") == "checkpoint":
                clip_src = [loader_id, 1]
            elif g.has("clip"):
                clip_src = [g.id_of("clip"), 0]
            g.insert_lora_chain(loras, model_src, clip_src)

        # --- prompts ---------------------------------------------------------
        transform = fam.get("prompt_transform")
        pos = G.apply_prompt_transform(p.get("positive", ""), transform)
        neg = G.apply_prompt_transform(p.get("negative", ""), transform)
        g.set_input("encode_pos", "text", pos)
        g.set_input("encode_neg", "text", neg)

        # --- latent ----------------------------------------------------------
        latent_cls = fam.get("latent_class", "EmptyLatentImage")
        if latent_cls != "EmptyLatentImage":
            g.set_class("latent", latent_cls)
        w, h = p.get("width"), p.get("height")
        if not w or not h:
            res = fam.get("resolution") or {}
            w, h = calc_dims(res.get("aspect", "1:1"), res.get("megapixels", 1.0),
                             res.get("multiple", 64))
        g.set_input("latent", "width", int(w))
        g.set_input("latent", "height", int(h))
        g.set_input("latent", "batch_size", int(p.get("batch_size", 1)))

        # --- sampling --------------------------------------------------------
        g.set_input("sampler_select", "sampler_name", p.get("sampler_name", "euler"))
        g.set_input("scheduler", "scheduler", p.get("scheduler", "simple"))
        g.set_input("scheduler", "steps", int(p.get("steps", 20)))
        g.set_input("scheduler", "denoise", float(p.get("denoise", 1.0)))
        g.set_input("sampler", "cfg", float(p.get("cfg", 1.0)))
        g.set_input("sampler", "noise_seed", int(p.get("seed", 0)))
        g.set_input("sampler", "add_noise", bool(p.get("add_noise", True)))
        g.set_input("save", "filename_prefix", p.get("filename_prefix", "painter"))

        prompt = g.to_prompt()
        if object_info is not None:
            problems = G.validate(prompt, object_info)
            if problems:
                raise G.ValidationError(problems)
        return {
            "prompt": prompt,
            "pairing": pairing,
            "params": {**p, "positive": pos, "negative": neg,
                       "width": int(w), "height": int(h), "toggles": toggles},
        }


    # -- editing -------------------------------------------------------------

    def _build_edit(self, entry, fam, g, p, pairing, object_info):
        """The edit branch of build(): one image in, one prompt, one image out.

        Everything about the size is decided by the dropped image — it is scaled
        to the family's pixel budget and `GetImageSize` feeds both the latent and
        Flux2Scheduler — so there is no aspect, no width/height and no batch of
        different shapes to reconcile.  The negative conditioning is the positive
        one ZEROED OUT rather than a second prompt, which is why the negative box
        is gone rather than typed into nothing (the same rule the video branch
        follows for its own missing controls).
        """
        spec = fam.get("edit") or {}
        # The FIRST image is the primary: it alone sizes the output (GetImageSize
        # feeds the latent and the scheduler). `input_images` is the full list;
        # `input_image` is the legacy single field and equals its first element.
        images = [str(s).strip() for s in (p.get("input_images") or []) if str(s).strip()]
        image = (p.get("input_image") or (images[0] if images else "")).strip()
        if not image:
            raise G.GraphError("drop an image to edit first")
        if not images:
            images = [image]

        # --- LoRA chain (same shape as the image path; there IS a clip here) ---
        loras = p.get("loras") or []
        if loras:
            g.insert_lora_chain(loras, [g.id_of("loader"), 0], [g.id_of("clip"), 0])

        pos = G.apply_prompt_transform(p.get("positive", ""), fam.get("prompt_transform"))
        g.set_input("encode_pos", "text", pos)
        g.set_input("load_image", "image", image)

        mp = float(p.get("megapixels") or spec.get("megapixels", 1.5))
        upscale = spec.get("upscale_method", "nearest-exact")
        res_steps = int(spec.get("resolution_steps", 1))
        g.set_input("scale_image", "megapixels", mp)
        g.set_input("scale_image", "resolution_steps", res_steps)
        g.set_input("scale_image", "upscale_method", upscale)

        # --- ADDITIONAL reference images ------------------------------------
        # Flux 2 attaches every reference latent as a CONDList (comfy's
        # Flux.extra_conds sums them), so N images are N chained ReferenceLatent
        # nodes -- each its own LoadImage -> scale -> VAEEncode -- appended onto
        # BOTH conditioning tails. ReferenceLatent's own schema: "If the model
        # supports it you can chain multiple to set multiple reference images."
        # Only the primary (above) sizes the output; the rest are references.
        pos_tail = [g.id_of("ref_pos"), 0]
        neg_tail = [g.id_of("ref_neg"), 0]
        for i, ref in enumerate(images[1:], start=2):
            li = g.add_node("LoadImage", {"image": ref},
                            f"load_image_{i}", f"Load Image {i}")
            si = g.add_node("ImageScaleToTotalPixels",
                            {"upscale_method": upscale, "megapixels": mp,
                             "resolution_steps": res_steps, "image": [li, 0]},
                            f"scale_image_{i}", f"Scale Image {i}")
            ve = g.add_node("VAEEncode",
                            {"pixels": [si, 0], "vae": [g.id_of("vae"), 0]},
                            f"vae_encode_{i}", f"VAE Encode {i}")
            rp = g.add_node("ReferenceLatent",
                            {"conditioning": list(pos_tail), "latent": [ve, 0]},
                            f"ref_pos_{i}", f"Set Reference Latent {i}")
            rn = g.add_node("ReferenceLatent",
                            {"conditioning": list(neg_tail), "latent": [ve, 0]},
                            f"ref_neg_{i}", f"Set Reference Latent (negative) {i}")
            pos_tail, neg_tail = [rp, 0], [rn, 0]
        if len(images) > 1:
            g.set_input("guider", "positive", pos_tail)
            g.set_input("guider", "negative", neg_tail)

        g.set_input("model_sampling", "shift", float(p.get("shift", spec.get("shift", 6.0))))
        g.set_input("sampler_select", "sampler_name", p.get("sampler_name", "euler"))
        g.set_input("scheduler", "steps", int(p.get("steps", 15)))
        g.set_input("guider", "cfg", float(p.get("cfg", 1.0)))
        g.set_input("noise", "noise_seed", int(p.get("seed", 0)))
        g.set_input("latent", "batch_size", int(p.get("batch_size", 1)))
        g.set_input("save", "filename_prefix",
                    p.get("filename_prefix", spec.get("filename_prefix", "painter-edit")))

        prompt = g.to_prompt()
        if object_info is not None:
            problems = G.validate(prompt, object_info)
            if problems:
                raise G.ValidationError(problems)
        params = {**p, "positive": pos, "negative": "", "kind": "edit",
                  "megapixels": mp, "input_image": image,
                  "input_images": images, "edit": True}
        # What the recorded parameters must NOT claim: Flux2Scheduler takes a
        # step count and the image's size and nothing else, so the family's
        # image-path scheduler/denoise/add_noise would be three settings the PNG
        # says were used and were not (docs/DESIGN.md §10, and "inject params"
        # would put them back into a job that ignores them).
        for unused in ("scheduler", "denoise", "add_noise", "width", "height",
                       "aspect", "multiple"):
            params.pop(unused, None)
        return {"prompt": prompt, "pairing": pairing, "params": params}

    # -- video --------------------------------------------------------------

    def _build_video(self, entry, fam, g, p, pairing, object_info):
        """The video branch of build(): one template, two modes.

        Image-to-video keeps the LoadImage -> scale -> GetImageSize chain, so
        the frame size comes out of the dropped image and the only size control
        is the pixel budget.  Text-to-video drops that chain and takes painter's
        own aspect + MP.  Nothing else differs between the two.
        """
        spec = fam.get("video") or {}
        fps = float(p.get("fps", spec.get("fps", 24.0)))
        mp = float(p.get("megapixels") or (fam.get("resolution") or {}).get("megapixels", 0.3))
        image = (p.get("input_image") or "").strip() if p.get("use_input_image") else ""
        last = (p.get("last_image") or "").strip() if p.get("use_last_frame") else ""

        # --- LoRA chain (same shape as the image path) ------------------------
        loras = p.get("loras") or []
        if loras:
            g.insert_lora_chain(loras, [g.id_of("loader"), 0], None)

        # --- prompt (the node takes it raw; there is no CLIPTextEncode) -------
        pos = G.apply_prompt_transform(p.get("positive", ""), fam.get("prompt_transform"))
        g.set_input("video", "prompt", pos)

        frames = video_frames(p.get("duration", spec.get("duration", 5.0)), fps,
                              int(spec.get("min_frames", 5)),
                              int(spec.get("frame_chunk", 17)))
        g.set_input("video", "length", frames)

        if image or last:
            # TWO INDEPENDENT FRAMES. `first_frame` and `last_frame` are both
            # optional inputs on the node, so each dropped image is one more
            # link, not another graph: first only, last only, or both (the same
            # file in both makes the clip loop). The MEASURING chain still runs
            # off exactly one of them — the first when there is one, otherwise
            # the last — since the frame size comes out of a dropped image
            # whichever end it belongs to.
            if image:
                g.set_input("load_image", "image", image)
            else:
                g.set_input("scale_image", "image", [g.id_of("load_image_last"), 0])
                g.node("video").get("inputs", {}).pop("first_frame", None)
                g.drop("load_image")
            if last:
                g.set_input("load_image_last", "image", last)
                g.set_input("video", "last_frame", [g.id_of("load_image_last"), 0])
            else:
                g.drop("load_image_last")
            g.set_input("scale_image", "megapixels", mp)
            g.set_input("scale_image", "resolution_steps",
                        int((fam.get("resolution") or {}).get("multiple", 32)))
            g.set_input("scale_image", "upscale_method",
                        spec.get("upscale_method", "nearest-exact"))
            w = h = None
        else:
            w, h = p.get("width"), p.get("height")
            if not w or not h:
                res = fam.get("resolution") or {}
                w, h = calc_dims(res.get("aspect", "1:1"), mp, res.get("multiple", 32))
            # The size is a pair of numbers now, so the image chain has nothing
            # left reading it and can go (Graph.drop refuses if anything does).
            g.set_input("video", "width", int(w))
            g.set_input("video", "height", int(h))
            g.node("video").get("inputs", {}).pop("first_frame", None)
            g.drop("image_size")
            g.drop("scale_image")
            g.drop("load_image")
            g.drop("load_image_last")

        # --- sampling ---------------------------------------------------------
        g.set_input("sampler_select", "sampler_name", p.get("sampler_name", "res_multistep"))
        g.set_input("scheduler", "scheduler", p.get("scheduler", "simple"))
        g.set_input("scheduler", "steps", int(p.get("steps", 20)))
        g.set_input("scheduler", "denoise", float(p.get("denoise", 1.0)))
        g.set_input("noise", "noise_seed", int(p.get("seed", 0)))
        g.set_input("create_video", "fps", fps)
        g.set_input("create_video", "bit_depth", int(spec.get("bit_depth", 8)))
        g.set_input("save", "filename_prefix", p.get("filename_prefix", "video/painter"))

        prompt = g.to_prompt()
        if object_info is not None:
            problems = G.validate(prompt, object_info)
            if problems:
                raise G.ValidationError(problems)
        params = {**p, "positive": pos, "negative": "", "frames": frames,
                  "fps": fps, "megapixels": mp, "kind": "video",
                  "input_image": image, "use_input_image": bool(image),
                  "last_image": last, "use_last_frame": bool(last)}
        if w and h:
            params["width"], params["height"] = int(w), int(h)
        return {"prompt": prompt, "pairing": pairing, "params": params}


def video_frames(duration: float, fps: float, min_frames: int = 5, chunk: int = 17) -> int:
    """Seconds -> the frame count the model will accept.

    MiniMax H3 packs frames in groups of 17 after a first one, so a length has
    to be congruent to `min_frames` mod `chunk`; the source workflow expressed
    this as a ComfyMathExpression and 5s at 24fps came out as 124.  It is four
    lines of arithmetic, so painter does it here rather than depending on a
    custom node.
    """
    n = max(int(min_frames), int(round(float(duration) * float(fps))))
    n += (int(min_frames) - (n % int(chunk))) % int(chunk)
    return int(n)


def calc_dims(aspect: str, megapixels: float, multiple: int = 64):
    """Width/height for an aspect ratio at a target pixel count."""
    try:
        aw, ah = (float(x) for x in str(aspect).split(":"))
    except ValueError:
        aw = ah = 1.0
    total = max(megapixels, 0.05) * 1_000_000
    import math

    h = math.sqrt(total * ah / aw)
    w = h * aw / ah
    q = max(int(multiple), 1)
    w = max(q, int(round(w / q)) * q)
    h = max(q, int(round(h / q)) * q)
    return int(w), int(h)


# ---------------------------------------------------------------------------


def _main(argv):
    import argparse

    ap = argparse.ArgumentParser(description="Inspect painter's model registry.")
    ap.add_argument("--root", default=MODEL_ROOT)
    ap.add_argument("--pair-all", action="store_true")
    ap.add_argument("--lora-matrix", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)

    reg = Registry(args.root, use_cache=not args.no_cache)
    rc = 0

    if args.list or not (args.pair_all or args.lora_matrix):
        for role in ("diffusion", "checkpoint", "text_encoder", "vae", "lora"):
            items = reg.by_role.get(role) or []
            print(f"\n=== {role} ({len(items)}) ===")
            for e in items:
                print(f"  {e.name:<56} {e.family}")

    if args.pair_all:
        print("\n=== pairing ===")
        for e in reg.base_models():
            r = reg.pair(e)
            enc = r["encoder"].name if r["encoder"] else "-"
            vae = r["vae"].name if r["vae"] else "-"
            status = "OK " if not r["problems"] else "FAIL"
            if r["problems"]:
                rc = 1
            print(f"  {status} {e.name:<52} {e.family:<14} {enc:<34} {vae}")
            for p in r["problems"]:
                print(f"        ! {p}")

    if args.lora_matrix:
        bases, seen = [], set()
        for e in reg.base_models():
            if e.family not in seen:
                seen.add(e.family)
                bases.append(e)
        print("\n=== lora compatibility ===")
        print(f"{'lora':<48}" + "".join(f"{b.family[:11]:>13}" for b in bases))
        for lora in reg.loras():
            row = ""
            for b in bases:
                v = reg.lora_compat(lora, b)
                cell = ("YES" if v["ok"] else ".") + " %.0f%%" % (v["score"] * 100)
                row += "%13s" % cell
            print(f"{lora.name[:47]:<48}{row}")
    return rc


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
