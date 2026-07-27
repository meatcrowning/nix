# `painter` — text-to-image app

Vendored source of the standalone Qt/QML text-to-image app (`main.py`, `qml/`,
`families/`, `graphs/`, `tools/`), same live-source pattern as the rest of
[`apps/`](../AGENTS.md). Built/installed by `home/prog/painter.nix` (mirrors
`player.nix`, plus `qt6.qtwebsockets`); runs the **live** source, so `.py`/`.qml`
edits need no rebuild.

Front end for a **headless ComfyUI** — the app speaks only the HTTP/ws API
(`/prompt`, `/object_info`, `/ws`, `/view`, `/history`, `/interrupt`, `/queue`),
so a Comfy update cannot break the UI, only individual node contracts (which
`graph.py` checks against the live `/object_info` at build time and reports as a
per-family reason string rather than a silent failure). Chrome is hyprvtb
titlebar buttons (generate/cancel/view switch + bottom-anchored settings
drawer).

**Every scrollable surface here is a `Kinetic*` view from `../qmlcommon/`** — the gallery grid, the model/LoRA/dropdown lists, the left parameter column and the prompt boxes. painter used to carry its own copy of `WheelScroll.qml` that nothing imported, so every one of those was a bare Flickable adding Qt's flick on top of the compositor's momentum. Never write a bare `ListView`/`GridView`/`Flickable` here; see [`../AGENTS.md`](../AGENTS.md).

## The backend is NOT packaged

ComfyUI stays the venv+`nix-shell` checkout at `/home/lam/comfy` (symlink →
`Downloads/git/ComfyUI`, v0.26.0); its `shell.nix` already pins nixpkgs-24.11,
installs torch cu128 and patchelfs Triton's `ptxas` for NixOS, which is the
hard-won part. `home/prog/painter.nix` only adds a `systemd --user` unit
`comfy-painter.service` (no `[Install]`, never starts at boot) that painter
starts on demand and deliberately does **not** stop on exit, so 8-16G of weights
stay warm between launches. Logs: `journalctl --user -u comfy-painter -f`.

The unit passes `--listen 127.0.0.1`, and that is a **security boundary, not a
default**: ComfyUI has no authentication and a workflow graph is arbitrary code
with filesystem access. Never rebind it to `0.0.0.0`, and never add 8188 to the
tailnet allowlist in `sys/net/tailscale.nix`. To drive top's backend from air,
tunnel it behind ssh's key auth:

```bash
apps/painter/tools/comfy-tunnel.sh            # start it on top, forward 8188
apps/painter/tools/comfy-tunnel.sh -- painter # ...and run painter over it
```

`comfy.py`'s `DEFAULT_URL` stays `http://127.0.0.1:8188` so the app needs no
configuration — it talks to the local end of the forward. `PAINTER_COMFY_URL`
overrides it, for a forward parked on another *local* port; pointing it at a
remote host would put the unauthenticated API on the wire.

## Models live at `/home/lam/models`

~246G — consolidated 2026-07-25 from the two former roots,
`Downloads/git/ComfyUI/models` and `Projects/cte/app/models`, both of which are
now **symlinks** to it; that keeps cte working without editing its `config.py`,
which regenerates its own `extra_model_paths.yaml` on every import. Never in
git. Reached only via `/home/lam/models/extra_model_paths.yaml`.

## Model identification is by tensor header, not filename

`fingerprint.py`, pure stdlib, whole 246G collection in ~0.2s: safetensors' JSON
header and GGUF's KV block give tensor names and shapes, and the rules mirror
`comfy/model_detection.py` — which is the authority to re-check when a Comfy
bump moves a signal. Consequences worth remembering:

- GGUF `general.architecture` **lies** (both Krea 2 GGUFs claim `qwen_image`),
  so never key on it.
- `qwen_image_vae` and `wan21-vae` are structurally identical, so VAE identity
  needs a hash/name fallback.
- LoRA compatibility is scored by recovering the target key namespace and
  intersecting it with the base model's, which needs a per-family **alias map**
  (Krea 2 LoRAs say `text_fusion`/`to_k`/`to_gate` where the base says
  `txtfusion`/`wk`/`gate`; Z-Image LoRAs address `to_q`/`to_k`/`to_v` that the
  base keeps fused as `attention.qkv`).

Unrecognised files stay visible in the picker with a family dropdown;
assignments persist in `~/.local/state/painter/overrides.json`.

## One graph, not one per model

`graphs/universal.json`; the sole exception is `universal_ckpt.json` for bundled
checkpoints, which need `CheckpointLoaderSimple` instead of the loader/clip/vae
trio. Per-family difference is expressed three ways only: a value, an optional
node spliced in/out, or a node-class swap at one role
(`UNETLoader`/`UnetLoaderGGUF`/`OTUNetLoaderW8A8` — a GGUF physically cannot
load on the plain loader).

Nodes are addressed by `_meta.painter_role`, **never by node id**, and
`_meta.painter_bypass` maps an output back to the input that replaces it when a
node is removed.

Two optional nodes are user toggles: `CLIPNegPip` (from `ComfyUI-ppm` — it is
what makes `(tag:-1.0)` work *inside* the positive prompt, and note the positive
encode reads the patched CLIP while the negative reads the raw one) and
`ModelSamplingSD3Advanced` with its full parameter set. **Chroma must keep
NegPip off**: ppm patches Flux's forward, which expects a `time_in` layer Chroma
replaces with `distilled_guidance_layer`, and enabling it aborts the sampler.

## Per-family prompt transforms

Anima's prompts are flattened to a single line on the way out
(`prompt_transform: single_line`) while the editor keeps your line breaks;
everything else is passed through verbatim (Krea 2's `<think>…</think>` prose
must not be touched). The string actually sent is what gets recorded in the PNG.

## Adding a family

Drop a `families/<id>.json`. No code, no new graph. Verify with
`tools/validate-graphs.py` (every family × all four toggle combinations, checked
against live `/object_info`), `registry.py --pair-all`,
`registry.py --lora-matrix`, and `tools/coverage-test.py`, which actually runs
**every** base model for one step — 19/19 as of 2026-07-25, including the
int8-convrot loader, three GGUFs, both bundled checkpoints, and the pixel-space
`zeta-chroma`, which needs the generated `vae/pixel_space_vae_stub.safetensors`
(a 220-byte file whose only tensor is named `pixel_space_vae`; `comfy/sd.py`
matches on that key alone). `tools/consolidate.py` did the model move and writes
an inverse-`mv` rollback script before touching anything.
