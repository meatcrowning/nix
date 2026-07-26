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
            out["vae"] = self._pick_vae(fam, ov)
            if out["encoder"] is None:
                want = (fam.get("text_encoder") or {}).get("te_model")
                out["problems"].append(f"no text encoder of type {want} found")
            if out["vae"] is None:
                want = (fam.get("vae") or {}).get("arch")
                out["problems"].append(f"no {want} VAE found")
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

    def _pick_vae(self, fam, ov):
        if ov.get("vae"):
            v = self.find(ov["vae"])
            if v:
                return v
        spec = fam.get("vae") or {}
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

        g = G.Graph(G.load_template(fam.get("graph", "universal.json")))
        defaults = self.defaults_for(entry)
        p = {**defaults, **(params or {})}

        # --- loader ---------------------------------------------------------
        if fam.get("loader_shape") == "checkpoint":
            g.set_input("loader", "ckpt_name", entry.name)
        else:
            loader = entry.loader or "UNETLoader"
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
