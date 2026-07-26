# NixOS Configuration Reference

This file provides a high-level overview of the configuration structure and key features for future reference and AI agents.

## Project Structure Overview

The configuration is split into three main areas: System-wide NixOS settings, User-specific Home Manager settings, and Machine-specific host definitions.

- `flake.nix`: The entry point for the entire configuration. Defines inputs (nixpkgs, home-manager, etc.), orchestrates the `top` NixOS configuration, and exposes a standalone `homeConfigurations.air` for a second, non-NixOS machine.
- `hosts/`: Contains machine-specific configurations.
    - `hosts/top/`: Configuration for the primary host "top" (full NixOS, x86_64-linux).
- **`air`**: a MacBook Air running Fedora Asahi Remix (aarch64-linux), OS hostname `book`. Not NixOS — it only gets `home-manager` layered on top of the existing Fedora install via `homeConfigurations.air` (`home-manager.lib.homeManagerConfiguration` in `flake.nix`, reusing `./lam.nix`/`home/` unchanged). It has no `hosts/air/` or system-level config — `sys/*` is NixOS-only and doesn't apply. Activate/update with `home-manager switch --flake /home/lam/nix#air`.
- `sys/`: System-wide NixOS modules and configurations.
    - Uses a recursive importer in `sys/default.nix` to automatically include all `.nix` files in this tree.
    - `sys/options.nix`: Defines custom options (e.g., `my.aerotheme.enable`).
    - `sys/dsk/`: Desktop environment configurations (Plasma, Hyprland).
- `home/`: Home Manager configuration for the user `lam`.
    - Also uses a recursive importer in `home/default.nix`.
    - `home/pkgs/`: Categories of packages (base, dev, game, media, etc.).
    - `home/prog/`: Program-specific configurations (zsh, bash, mpv, etc.).
- `lam.nix`: The entry point for the Home Manager configuration, which imports the `home/` directory.
- `filer/`: Vendored source of the standalone Qt/QML file browser (its own self-contained flake — `main.py`, `qml/`). Lives at the repo top level **on purpose**: it must stay outside `home/`/`sys/`, whose `umport` recursively imports every `.nix` file (it would try to eval filer's `flake.nix` as a module). Nothing in the NixOS/home evaluation imports `filer/` — it's inert vendored source that simply travels with the repo. The `filer` binary is built and installed by `home/prog/filer.nix`, which wraps `python3` around the **live** source at `/home/lam/nix/filer/main.py` (absolute path, valid on both `top` and `air`), so QML/Python edits are picked up with no rebuild. A compat symlink `~/Projects/filer → ~/nix/filer` preserves the old source path. filer's own flake builds on `x86_64-linux` + `aarch64-linux` (`nix run ~/nix/filer` / `run.sh` work on book too).
- `viewer/`: Vendored source of the standalone Qt/QML **image viewer** (its own self-contained flake — `main.py`, `qml/`), same top-level-on-purpose rationale as `filer/` (kept outside `home/`/`sys/` so `umport` doesn't eval its `flake.nix`). Split out of filer's old built-in overlay: filer's `openFile` now shells out to `viewer <path>`, and viewer scans that file's directory for the sibling images so ‹/› flip through the folder. Built/installed by `home/prog/viewer.nix` (mirrors `filer.nix`, including the `air` system-python split); runs the **live** source at `/home/lam/nix/viewer/main.py`, so edits need no rebuild. Its prev/next/zoom/fit/close controls live in the hyprvtb titlebar (same `pylib/vtbclient.py` bridge filer/surfer use).
- `player/`: Vendored source of the standalone Qt/QML **music player** (`main.py`, `qml/`), same top-level-on-purpose rationale as `filer/`/`viewer/`. Tag-driven library (background mutagen scan of `/run/media/lam/SSD/aud` → `~/.local/share/player/library.db`, art thumbs in `~/.cache/player/art/`), libmpv playback (python-mpv), MPRIS via `mpris-server` (the panel's MediaPanel controls it), FMPS rating/playcount/favourite tag writeback (journaled to `~/.local/state/player/tagwrites.log`, gated by prefs `tagWrites: off|log|on`, ships in `log`), synced lyrics, ReplayGain volume levelling. Built/installed by `home/prog/player.nix` (mirrors `viewer.nix`); runs the **live** source, so `.py`/`.qml` edits need no rebuild — relaunch the app. ALL chrome is hyprvtb titlebar buttons (transport + view switcher + sort + search toggle + a bottom-anchored settings button whose drawer — surfer's `dm`-panel idiom — holds rescan and the album gallery's live column count) + the `PLAYBAR`/`SEEK` scrub bar; the pushed playbar fraction is floored at 0.002 because plugin builds ≤2.44 abort the compositor on a zero-height fill rect (fixed plugin-side in v2.45 — guard every computed rect when adding hyprvtb drawing).
  - **Lyrics + ReplayGain (2026-07-25).** `player/lyrics.py` is a Qt-free module shared by the app and `player/tools/lyrics-sync.py`: LRC parse, embedded read/write (LRC text in USLT / `LYRICS` / `©lyr` — *not* ID3 `SYLT`, which nothing reads), and a strict LRCLIB client. Resolution is **timestamped-first**: embedded synced → sidecar `.lrc` → LRCLIB, and a plain unsynced tag never ends the search (≈18% of this library has plain words sitting in its tags, which used to block the lookup permanently). Fetched synced lyrics are **written back into the file** (pref `lyricsEmbed`, default on; journaled to `tagwrites.log`). Two rules learned the hard way here: (1) matching must be STRICT because this writes to files — NetEase's search always returns a top hit and was observed matching "Wu-Lu — Run Away Dream" to an unrelated Chinese pop song, so it is deliberately NOT used as a fallback; (2) **there are THREE negative verdicts, not one**, because "this track has no words" and "nobody has indexed them" are different claims and only the first is knowable: `instrumental` (LRCLIB's flag — permanent, pane collapses), `instrumental-user` (marked by hand from the pane — permanent and undoable), and `none` (undetermined — retried on a widening backoff, 7/14/28…180d, via `lyrics.attempts`). **Do not try to infer instrumental from titles or genre**: an audit found only 163 of 11k titles carry any marker, catching 11 of the first 770 misses, and `Intro`/`Interlude`/`skit` often *do* have lyrics. The miss pile really is mixed — wordless ambient sits next to vocal tracks too obscure to index (Coaltar of the Deepers, Astrid Sonne) — so the only thing that could settle the rest is analysing the audio for singing, which is deliberately NOT built. Title/artist normalisation (`(Monopoly mix)`, `(ft. X)`, `prod. Y`) lifted the sample hit rate 42%→60%. `tools/lyrics-sync.py` sweeps the library: dry run by default, `--write` to embed, `--embed-cached` to do the file writes with no network (the split exists because looking up 11k tracks is harmless while music plays, whereas rewriting tags under the running player is not — the tool refuses `--write` if `player/main.py` is up). ReplayGain: the scan mirrors `REPLAYGAIN_*`/`R128_*` (all three tag families; MP4 freeform names must be matched case-insensitively — some files say `com.apple.itunes`) into new `tracks.rg_*` columns, and **mpv applies the gain itself** (`replaygain`/`-preamp`/`-fallback`/`-clip`), independent of the volume slider — verified empirically at −6.3 dB measured vs −6.32 dB tagged. ~96% of the library is already tagged; untagged files use the library's **median** gain rather than a made-up constant. NB when integrity-checking tag writes: `ffmpeg -i f -f md5 -` is **nondeterministic** on files with embedded cover art — hash audio only (`-map 0:a -f s16le - | md5sum`).
  - **Sharing the library with `air` (2026-07-25).** `air` has ~12 GB free and the library is 208 GB, so it is never copied — `sys/net/share.nix` serves `/run/media/lam/SSD/aud` over SMB (samba, not NFS: exFAT has no `export_operations` for nfsd) plus avahi (`top.local`) and keys-only sshd, every port scoped to `enp12s0`; `sys/disks.nix` declares the SSD so it is up before a session is. **The one invariant everything rests on: `air` mounts the share at the SAME absolute path**, which makes `top`'s database valid there verbatim — no path rewriting, no rescan (measured: mtime passes through exFAT-over-SMB3 byte-exact for all 11 099 tracks). Metadata is reconciled by `player/tools/dbsync.py` (`pull`/`push`/`sync`/`status`), keyed on `tracks.path` and never on `id`, stdlib-only so it runs under Fedora's python, and its own remote agent — it pipes ITSELF to `python3 -` over ssh. It never deletes, and a first pull **seeds** rather than merges (a locally-scanned db renumbers the rowids that `prefs.json`'s saved queue is made of). Two traps: snapshot with sqlite's `backup`, never `cp` (WAL); and `MIGRATIONS` entries are `(table, col, decl, rescan)` — adding a `tracks` column with `rescan=True` clears the mtime cache and forces an 11k-file re-read, which over SMB is brutal, so a column the APP writes (`meta_mtime`) must set it False. Full plan, runbook and STATUS: `docs/air-library-share.md`. Part B (on `air`) has not been run.
  - **Spotify export → what's missing locally (2026-07-25).** `player/tools/spotify-dump.py` exports the account's Spotify library (Authorization Code + **PKCE**, so no client secret exists to leak; token cached 0600 in `~/.local/state/spotify-dump/`, client id kept out of this public tree) and `player/tools/spotify-missing.py` diffs it against `library.db` into matched/suspect/**missing** TSVs — the last being the work list for finding copies elsewhere. Both stdlib-only, same reason as `dbsync.py`. Three things worth knowing before touching them: (1) **`GET /playlists/{id}/tracks` no longer exists** — Spotify's Feb–Mar 2026 migration replaced it with `/playlists/{id}/items` and renamed each entry's `track` key to `item`; the old path 403s unconditionally and `/me/playlists` reports `tracks:null`, so there is no fallback. (2) A **Development-mode** app gets playlist *contents* only for playlists the user created or collaborates on (14 of 92 here are other people's, metadata only), so a per-playlist 403 is normal and must never abort the run. (3) The local db has **no ISRC column**, so the diff cannot use the ISRCs the dump collects — matching is normalised artist+title with duration as a signal that *flags* (`suspect.tsv`) rather than rejects. Adding `isrc` to the scan would mean a `MIGRATIONS` entry with `rescan=True`, i.e. a full 11k-file re-read.
  - **`pylib/trackmatch.py` owns artist/title normalisation.** It was extracted from `player/lyrics.py`, which imports `mutagen` and therefore cannot be imported by anything running under a bare `python3`. `lyrics.py` imports it back under its historical private names (`_fold`, `_title_matches`, …), so behaviour there is unchanged. **Any new "are these two tag strings the same song?" code must use this module** rather than grow a second copy — the decoration stripping is what took the LRCLIB hit rate from 42% to 60%, and a drifting duplicate would silently regress that.
- `painter/`: Vendored source of the standalone Qt/QML **text-to-image app** (`main.py`, `qml/`, `families/`, `graphs/`, `tools/`), same top-level-on-purpose rationale as `filer/`/`viewer/`/`player/`. Front end for a **headless ComfyUI** — the app speaks only the HTTP/ws API (`/prompt`, `/object_info`, `/ws`, `/view`, `/history`, `/interrupt`, `/queue`), so a Comfy update cannot break the UI, only individual node contracts (which `graph.py` checks against the live `/object_info` at build time and reports as a per-family reason string rather than a silent failure). Built/installed by `home/prog/painter.nix` (mirrors `player.nix`, plus `qt6.qtwebsockets`); runs the **live** source, so `.py`/`.qml` edits need no rebuild. Chrome is hyprvtb titlebar buttons (generate/cancel/view switch + bottom-anchored settings drawer).
  - **The backend is NOT packaged.** ComfyUI stays the venv+`nix-shell` checkout at `/home/lam/comfy` (symlink → `Downloads/git/ComfyUI`, v0.26.0); its `shell.nix` already pins nixpkgs-24.11, installs torch cu128 and patchelfs Triton's `ptxas` for NixOS, which is the hard-won part. `home/prog/painter.nix` only adds a `systemd --user` unit `comfy-painter.service` (no `[Install]`, never starts at boot) that painter starts on demand and deliberately does **not** stop on exit, so 8-16G of weights stay warm between launches. Logs: `journalctl --user -u comfy-painter -f`.
  - **Models live at `/home/lam/models`** (~246G — consolidated 2026-07-25 from the two former roots, `Downloads/git/ComfyUI/models` and `Projects/cte/app/models`, both of which are now **symlinks** to it; that keeps cte working without editing its `config.py`, which regenerates its own `extra_model_paths.yaml` on every import). Never in git. Reached only via `/home/lam/models/extra_model_paths.yaml`.
  - **Model identification is by tensor header, not filename** (`fingerprint.py`, pure stdlib, whole 246G collection in ~0.2s): safetensors' JSON header and GGUF's KV block give tensor names and shapes, and the rules mirror `comfy/model_detection.py` — which is the authority to re-check when a Comfy bump moves a signal. Consequences worth remembering: GGUF `general.architecture` **lies** (both Krea 2 GGUFs claim `qwen_image`), so never key on it; `qwen_image_vae` and `wan21-vae` are structurally identical, so VAE identity needs a hash/name fallback; and LoRA compatibility is scored by recovering the target key namespace and intersecting it with the base model's, which needs a per-family **alias map** (Krea 2 LoRAs say `text_fusion`/`to_k`/`to_gate` where the base says `txtfusion`/`wk`/`gate`; Z-Image LoRAs address `to_q`/`to_k`/`to_v` that the base keeps fused as `attention.qkv`). Unrecognised files stay visible in the picker with a family dropdown; assignments persist in `~/.local/state/painter/overrides.json`.
  - **One graph, not one per model** (`graphs/universal.json`; the sole exception is `universal_ckpt.json` for bundled checkpoints, which need `CheckpointLoaderSimple` instead of the loader/clip/vae trio). Per-family difference is expressed three ways only: a value, an optional node spliced in/out, or a node-class swap at one role (`UNETLoader`/`UnetLoaderGGUF`/`OTUNetLoaderW8A8` — a GGUF physically cannot load on the plain loader). Nodes are addressed by `_meta.painter_role`, **never by node id**, and `_meta.painter_bypass` maps an output back to the input that replaces it when a node is removed. Two optional nodes are user toggles: `CLIPNegPip` (from `ComfyUI-ppm` — it is what makes `(tag:-1.0)` work *inside* the positive prompt, and note the positive encode reads the patched CLIP while the negative reads the raw one) and `ModelSamplingSD3Advanced` with its full parameter set. **Chroma must keep NegPip off**: ppm patches Flux's forward, which expects a `time_in` layer Chroma replaces with `distilled_guidance_layer`, and enabling it aborts the sampler.
  - **Per-family prompt transforms**: Anima's prompts are flattened to a single line on the way out (`prompt_transform: single_line`) while the editor keeps your line breaks; everything else is passed through verbatim (Krea 2's `<think>…</think>` prose must not be touched). The string actually sent is what gets recorded in the PNG.
  - Adding a family = drop a `families/<id>.json`. No code, no new graph. Verify with `tools/validate-graphs.py` (every family x all four toggle combinations, checked against live `/object_info`), `registry.py --pair-all`, `registry.py --lora-matrix`, and `tools/coverage-test.py`, which actually runs **every** base model for one step — 19/19 as of 2026-07-25, including the int8-convrot loader, three GGUFs, both bundled checkpoints, and the pixel-space `zeta-chroma`, which needs the generated `vae/pixel_space_vae_stub.safetensors` (a 220-byte file whose only tensor is named `pixel_space_vae`; `comfy/sd.py` matches on that key alone). `tools/consolidate.py` did the model move and writes an inverse-`mv` rollback script before touching anything.

- `surfer/`: Vendored source of the standalone QtWebEngine **browser** (same live-source, top-level-on-purpose pattern as `filer/`; built/installed by `home/prog/surfer.nix`). Titlebar chrome via hyprvtb like the others.
- `pylib/`: shared Python helpers for the vendored apps — most importantly `vtbclient.py`, the hyprvtb titlebar-button socket bridge used by filer/viewer/surfer/player/painter.
- `tools/`: repo maintenance scripts that the documented workflows depend on: `preflight.sh` (THE pre-rebuild gate — untracked-file check + rootless eval + seed-drift; run it before every `sudo rebuild-top`), `seed-drift.sh` (seed-once source/live diff), `prune-worktrees.sh` (agent-worktree cleanup, aliased `wtprune`), `sandbox.sh` (an off-screen virtual monitor to test GUI changes on, so agents never open windows on the user's screen — see the desktop-shell section).
- `sounds/`: **git submodule** → `github.com/meatcrowning/vista-sounds` (a PRIVATE repo). Holds the Windows Vista event `.wav`s, which are Microsoft's and must NOT live in this public tree — so they're pulled in privately here. `home/srvs/vista-sounds.nix` exposes the checkout at the runtime path everything expects via an out-of-store symlink (`~/.local/share/sounds/vista → /home/lam/nix/sounds`), so a plain `git pull` picks up new sounds with no rebuild. **Cloning/pulling the config on a new machine (e.g. book) must use `--recurse-submodules`** (`git clone --recurse-submodules …`, or after a plain pull: `git submodule update --init`) or the sounds dir is empty; the private submodule also needs GitHub auth on that machine.

- `home/srvs/claude-memory.nix` + `claude-memory-files/`: two-way sync of Claude Code's **memory** files between `top` and `book`, via the PRIVATE repo `github.com/meatcrowning/claude-memories`. `~/.claude/projects` itself is the git checkout (in place — no copying), driven by the `claude-memory-sync.timer` user unit every 5 min; log at `~/.cache/claude-memory-sync.log`, force a run with `systemctl --user start claude-memory-sync.service`. Being under `home/`, it deploys to book automatically — that machine only needs `home-manager switch --flake ~/nix#air` plus a `gh auth login` (the git credential helper is `!gh auth git-credential`). **Two invariants worth protecting:** the `.gitignore` is an ALLOWLIST (ignore `*`, re-include only `*/memory/**`) because the same tree holds every session transcript, which must never be pushed; and `.gitattributes` sets `*.md merge=union` so a memory edited on both machines keeps both sides rather than wedging the sync on a conflict. Both are seeded from nix on every run, so edit them in `claude-memory-files/`, not in the live repo. Practical consequence: **a memory written on one machine is shared infrastructure** — a wrong one propagates, so say which host a fact is specific to.

- `docs/` + `home/srvs/nix-docs.nix`: the repo's working notes — plans, roadmaps, impact analyses, runbooks — collected out of five scattered directories into one place. **`docs/` is its own git repo against the PRIVATE remote `github.com/meatcrowning/nix-docs`, living inside this public checkout and listed in `.gitignore`.** So `git` run from `~/nix` does not see these files at all: commit from inside `docs/`, or let the timer do it. It syncs both ways between `top` and `book` every 5 min by **reusing `claude-memory-sync.sh` verbatim** — that script is parametrized by `CM_SYNC_REPO`/`REMOTE`/`LOG`/`SEED`/`LABEL`, so a second systemd user unit was all it took. Log at `~/.cache/nix-docs-sync.log`; force a run with `systemctl --user start nix-docs-sync.service`. **Deliberately not a submodule** (unlike `sounds/`): `git pull` does not update submodule contents, so the other machine would read a stale runbook — the exact friction this exists to remove. If you add a third caller of that script, you **must** override `CM_SYNC_SEED` — its default installs the memory store's ALLOWLIST `.gitignore`, which would silently untrack every file in your repo. Three docs stay put on purpose and `docs/README.md` says why; the load-bearing one is `home/prog/hyprvtb/PORTING.md`, cited by ten referrers including `checkPhase` failure messages, and inside the plugin's derivation source (moving it forces a rebuild + live plugin hot-swap).

## Key Features & Conventions

### Recursive Imports (`umport`)
Both `sys/` and `home/` use a helper function named `umport` (defined in their respective `default.nix` files). This function automatically imports every `.nix` file found recursively in those directories. Adding a new `.nix` file anywhere in these trees will automatically apply it to the configuration — including for `air`, since it consumes the same `home/` tree as `top` via `lam.nix`.

### Per-host branching (`host`)
`flake.nix` threads `host = "top"` or `host = "air"` into every `home/*.nix` module via `specialArgs`/`extraSpecialArgs` (take it as a module arg: `{ host, ... }:`). Use this — not a separate per-host file — for the rare line that must actually differ (see `home/prog/zsh.nix`'s rebuild aliases, `home/plasma.nix`'s `Xwayland.Scale`, `home/prog/hypr-host.nix`'s generated `host.lua` consumed by `home/prog/hypr-files/hyprland.lua`'s monitor scale). Everything else in `home/` is shared verbatim between both machines — that's the point of the split. Packages unavailable on aarch64-linux (proprietary x86_64-only binaries: `vcv-rack`, `pcsx2`, `vintagestory`, `google-chrome`, `wineWow64Packages`, `spotify`, `dwarf-fortress-packages`) are gated with `lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [...]` instead of `host ==`, since the real constraint is architecture, not the specific machine.

### Aerotheme Plasma Toggle
The `my.aerotheme.enable` option (defined in `sys/options.nix`) allows for easy switching between a standard Plasma 6 experience and the Windows-themed `aerothemeplasma`.
- **Location:** `hosts/top/configuration.nix` contains the master toggle.
- **Implementation:** `sys/dsk/plasma.nix` handles the conditional session switching and `aeroshell` activation.

### Hardware & Graphics
- `sys/hw/nvidia.nix`: Contains NVIDIA-specific drivers and configuration.
- `sys/gme/steam.nix`: Gaming and Steam-specific system settings.

### Desktop shell: Hyprland + Quickshell (`home/prog/`)

The live desktop is Hyprland driving a Quickshell panel. Source lives in
`home/prog/quickshell-files/` (the `.qml` panel) and `home/prog/hypr-files/`
(`hyprland.lua`), plus the `hyprvtb` Hyprland plugin (`home/prog/hyprvtb/`,
C++ — compositor-side window titlebars + session save/restore).

**Graceful session exit (logout / reboot / poweroff):** the power menu
(`PowerMenu.qml`) runs `quickshell-files/scripts/session-exit.sh` *before* the
power command for any `endSession` item. That script runs
`hyprctl eval "hl.plugin.hyprvtb.close_all()"`, which sends a graceful
`sendClose()` to every decorated non-scratch window — i.e. "clicks the [x]" —
then waits (bounded ~4s) for them to actually close before returning and
letting the power action fire. **That is its only job**: each app gets to save
its own state, and the plugin's `window.close` handler records the window's
geometry, which is what makes the app reopen where you left it next time.
It deliberately does NOT snapshot a session — logging in must not spawn
anything. `sleep` is NOT an `endSession` item (windows stay across suspend).

Session *snapshots* (`~/.local/state/hyprvtb/session.tsv`, relaunched by
`vtbRestoreSession` at the next fresh login) are a separate, deliberate act:
`hl.plugin.hyprvtb.save_session()` on Meta+Ctrl+S. Never call it from a script
— an unexpected snapshot means the next login spawns a pile of windows, and
restored windows skip the open-reveal animation by design.

**Plugin actions are Lua functions, never dispatchers.** `addDispatcherV2` is
useless under the Lua config: `hyprctl dispatch X` *evaluates X as a Lua
expression* and then wants a dispatcher object back, so a plugin dispatcher
name resolves to an undefined global and silently does nothing (the old
`hyprctl dispatch hyprvtbsaveclose` in `session-exit.sh` was a no-op for its
entire life — logout saved nothing and closed nothing gracefully; fixed in
v2.54). Register with `HyprlandAPI::addLuaFunction`, call from keybinds as
`hl.plugin.hyprvtb.<fn>()` and from scripts as
`hyprctl eval "hl.plugin.hyprvtb.<fn>()"`. Compositor bumps and the pinned
`hyprland` flake input are covered in `home/prog/hyprvtb/PORTING.md` — read it
before touching the plugin or the pin.

**Applying edits + reloading (READ THIS before editing panel/hypr config):**

- **Rebuild alias reality:** `rbhome`/`rbsys`/`update` all run `sudo rebuild-top`
  (a `writeShellScriptBin` wrapper that hardcodes
  `nixos-rebuild switch --flake /home/lam/nix#top`; `update` = `sudo rebuild-top
  --upgrade`). home-manager is a NixOS module here; there is no standalone
  `home-manager switch`, and `rbhome` is NOT a separate/dangerous command — on
  `top` it's the exact same rebuild as `rbsys`; see `home/prog/zsh.nix`. A
  NOPASSWD rule (`sys/nixos-rebuild.nix`) allows only that wrapper — **bare
  `sudo nixos-rebuild switch …` now PROMPTS** (the wrapper hard-scopes the
  flake/host so a NOPASSWD rule can't be abused into arbitrary-root). A **new**
  file must be `git add`-ed before the rebuild
  — the tree is dirty and flake eval ignores untracked files, so a brand-new
  `Foo.qml` is silently missing from the build otherwise.

- **Agents: just rebuild — don't ask, don't wait.** After any `~/nix` change,
  run the rebuild yourself as the final step, same standing autonomy as
  commit+push. The rebuild is **passwordless** (NOPASSWD rule in
  `sys/nixos-rebuild.nix`), so an agent CAN run **`sudo rebuild-top`**
  (or `sudo rebuild-top --upgrade`) non-interactively — no tty, no prompt. Note
  the NOPASSWD now covers **only the `rebuild-top` wrapper**, not bare
  `nixos-rebuild`, so use the wrapper — `sudo nixos-rebuild switch --flake …`
  will hang/fail on the missing tty. **Run `tools/preflight.sh` first** — it
  mechanizes the pre-rebuild ritual (untracked-`.nix`/`.qml` check, rootless
  eval of the top system, seed-drift) in ~10s with no sudo. (Optional: also
  pre-build with `nixos-rebuild build --flake …`, which needs no sudo at all,
  to warm the store first.) For any
  OTHER sudo command (one NOT covered by a NOPASSWD rule), use **`sudo -A`**:
  `SUDO_ASKPASS` is wired to a ksshaskpass dialog (`home/prog/askpass.nix`), so
  `sudo -A <cmd>` pops a password prompt to the user instead of failing on the
  missing tty. Plain `sudo <cmd>` (no `-A`, not NOPASSWD) just fails in an agent
  shell. Live-source apps (surfer/filer `.py`/`.qml`) still hot-reload with no
  rebuild; a rebuild is only needed when a change adds a dep or edits `.nix`
  packaging.

- **Most `quickshell-files/*` are Nix-store symlinks.** A rebuild swaps the
  symlinks but Quickshell watches the resolved store paths, so the swap does
  NOT trigger its hot-reload — the panel keeps running the old tree. Force a
  reload by modifying the ONE real file it watches, `~/.config/quickshell/
  Theme.qml`, **in place (same inode)** — e.g. append then restore a trailing
  comment (`printf '\n// x\n' >> Theme.qml` then `cat backup > Theme.qml`).
  Do NOT use `sed -i`/`mv` (rename = new inode = no reload), and note it
  **dedupes by content** so an identical rewrite is a no-op. A reload rebuilds
  only Quickshell's QML tree in-process (never touches Hyprland); a parse error
  keeps the old tree + fires a toast, so it can't crash the session.

- **A reload must look like a state change IN PLACE, not a re-entry** — that's
  the standing bar for anything on the desktop, because a wallpaper/theme change
  rewrites `Theme.qml` and so reloads the panel. Quickshell rebuilds the *whole*
  QML tree, so every widget otherwise comes back empty and visibly refills: the
  disk widget maps at its one-line "reading…" height and grows twice as its
  scripts land (dragging every in-place stackable above it up the screen), the
  forecast collapses until curl returns, cava restarts so the VU and spectrum
  drop to the floor, and the chart ring buffers restart from zero. Two
  mechanisms carry state across, both wired in `shell.qml`:
  - **the pin set** — mirrored to `$XDG_RUNTIME_DIR/qs-live-pins` and read back
    SYNCHRONOUSLY (`FileView { blockLoading: true }`) in `Component.onCompleted`,
    then applied with `snapPinned()`. The file's absence doubles as the
    login-vs-reload flag ($XDG_RUNTIME_DIR is wiped at logout). Pinning must
    ALWAYS trigger `SlidePopup`'s deferred layer remap, even pre-map: Quickshell
    latches the layer when it creates the window (at component completion,
    regardless of `visible`), so a pin applied during construction comes up on
    Overlay and every desktop widget floats ON TOP of windows. Check with
    `hyprctl layers` — the `qs-*` widget namespaces belong in level 1 (bottom).
  - **the widgets' contents** — a `PersistentProperties` block, which hands
    properties from the outgoing tree to the incoming one in-process. Each
    source exposes `stateJson()`/`restoreState()` plus a `stateRev` counter that
    `shell.qml` snapshots on; the 60fps VU/spectrum feeds are sampled on a
    250ms timer instead. **Two constraints, both found the hard way and both
    silent when violated:** it must be a DIRECT child of the root `Scope` (one
    level down inside a plain `Item` it never restores — a non-Reloadable parent
    breaks the matching chain), and every carried property must be a STRING —
    Quickshell alternates between two QML engines across reloads and a JSValue
    (any `property var` holding an array/object) can't move between them, so a
    `var` arrives `undefined` on every *other* reload with only a
    `JSValue can't be reassigned to another engine` warning to show for it.
    Restore fires after every `Component.onCompleted` but inside the same
    synchronous reload pass, so no frame renders in between.
    Verify with **`qs ipc call state carried`** — sizes of each carried blob
    plus the live buffer lengths. Poll it repeatedly across a forced reload:
    all non-zero and `cpuHist` counting up monotonically = the swap worked;
    a reset to 0 = something regressed.

- **Seed-once mutable files are NOT updated by rebuild:** `Theme.qml`,
  `hyprland.lua`, `hyprpaper.conf` are installed only if absent (they're
  rewritten in place at runtime by `wal-set.sh` / `cursor-recolor.sh` /
  hyprpaper). To change one, edit BOTH the nix source AND the live
  `~/.config/...` file **in place** (targeted string edit — never overwrite
  wholesale or you reset the live wal palette/border). Apply `hyprland.lua`
  changes with **`hyprctl reload`** (re-runs the live Lua, re-registers
  `hl.bind`s, does not disturb the session).

  **Run `tools/seed-drift.sh` whenever you touch one of these — before you
  start (to see what's already stale) and after you finish (to prove both
  copies moved).** It diffs each source/live pair with the runtime-owned values
  masked, so anything it prints is real drift; exit 1 = drift, `--quiet` for
  scripting. Adding a new seed-once file means adding it to the `PAIRS` list in
  that script.

  **Trap:** a fix applied to the nix source does nothing until it's ALSO put in
  the live file — the running system keeps the old behaviour indefinitely, and
  the reverse (live-only edit) is silently lost on the next fresh install.
  Editing only one side is the single most common way a change here appears to
  do nothing. This has bitten us repeatedly (a stale `focus workspace 50` line
  lived on in the live file long after it was removed from source, scattering
  windows across two workspaces; a later drift episode shipped a dead
  `SettingsStore` binding). Never trust a written claim about current drift
  state — run `tools/seed-drift.sh` for the live answer.

- **`hyprvtb` plugin (C++) — where to edit.** Hyprland comes from a *pinned*
  flake input (`hyprland.url = github:hyprwm/Hyprland/vX.Y.Z`), and the plugin
  is built against that exact package; bumping it is a deliberate act with a
  ritual — `home/prog/hyprvtb/PORTING.md`. Two containment rules the nix
  `checkPhase` enforces: volatile Hyprland internals may be named only in
  `vtbCompat.hpp` (everything else calls `Hl::…`), and a weak ref to a
  decoration must be a `CDecoRef`, never a raw `WP<CVtbDeco>` (a `lock()` over
  a unique-owned deco aborts the compositor).

- **The desktop's two moving parts are pinned; the rest of nixpkgs is not.**
  `nixpkgs` tracks `nixos-unstable`, but the compositor (`hyprland`, an exact
  upstream tag) and the shell (`nixpkgs-quickshell`, a whole nixpkgs frozen to
  one revision) do not — so a routine `nix flake update` can no longer carry
  in a new Hyprland or a new Quickshell and leave the session with no
  titlebars or no panel. Both inputs carry their full rationale in
  `flake.nix`; read it before touching either. Everything else — mesa, the
  NVIDIA driver, the kernel, Qt/PySide6, kitty, Plasma — still rolls, and
  still can break things, so `nixos-rebuild build` before `switch` and keep
  the previous generation in mind. Bump a pin **on its own commit**, never
  alongside other changes.

- **`hyprvtb` plugin (C++) reload after a source edit — `rbsys` then
  `hyprctl reload`. That is the whole procedure. NO relog, and never
  `hyprctl plugin load/unload`.** Bump the version string in `main.cpp` per
  change, then confirm `hyprctl plugin list` shows the **new Version**,
  **exactly one** hyprvtb, and `hyprctl configerrors` is empty. It briefly
  re-decorates every window (the plugin does session save/restore, so this is
  safe). If the tree is dirty, `git add` the changed files first — flake eval
  ignores untracked ones.

  This works because `hyprland.lua` passes `hl.plugin.load` the **resolved**
  `/nix/store/...` path (via `readlink -f`), not the stable symlink. Hyprland
  tracks config-loaded plugins by that literal path **string**, and
  `CPluginSystem::updateConfigPlugins` early-returns unless the string list
  *changes* between reloads. With the symlink the string was constant forever,
  so `hyprctl reload` was a no-op and the stale `.so` stayed mapped — which is
  what made everyone reach for manual `plugin load` and, historically, a relog.
  With the resolved path, each `rbsys` yields a new string and Hyprland does the
  swap itself, in the right order and with the right bookkeeping.

  **What makes the swap SURVIVABLE (2.65) — do not regress this.** A hot swap
  `dlclose()`s the old image while the compositor still holds pointers into it,
  and Hyprland's own cleanup is not enough:
  `HyprlandAPI::removeWindowDecoration` lands in `CWindow::removeWindowDeco`,
  which only queues the removal and calls `updateWindowDecos()` — and that
  early-returns on `!m_isMapped || isHidden()`. Every hidden window (this plugin
  hides rolled-up ones and parks minimized ones off-screen) therefore kept a
  `UP<CVtbDeco>` whose vtable was about to be unmapped, and the session
  SIGSEGV'd at the next window close, inside `~CWindow` under
  `CWindow::destroyWindow`. That is what took the desktop down on 2026-07-25.
  Three things now hold it together, all in `PLUGIN_EXIT`/`PLUGIN_INIT`:
  - `Hl::detachOurDecos()` erases this plugin's decorations from every window
    itself, uncaching them from the positioner, while its code is still mapped.
  - `CVtbDeco::restoreForUnload()` runs first, un-hiding rolled-up windows and
    un-parking minimized ones — states only this instance knows how to leave,
    which the incoming one does not inherit.
  - `PLUGIN_INIT` decorates hidden windows too (it used to skip them), so a
    minimized window isn't left with no titlebar at all after the swap.

  **A swap must also be INVISIBLE, not merely survivable (2.71).** Restoring
  every window on the way out is required, but it left them restored: a
  rolled-up window snapped open on `hyprctl reload` and stayed open. So
  `PLUGIN_EXIT` now writes the roll/minimize states to
  `~/.local/state/hyprvtb/handoff.tsv` before undoing them, and `PLUGIN_INIT`
  re-applies them (`toggleRollup(false)` — no animation) after it has decorated
  the existing windows. Keyed by window ADDRESS, which is only meaningful
  because a hot swap happens inside one compositor process; the file records
  that process's PID and is discarded on a mismatch, and consumed (deleted) on
  the first read either way, so nothing leaks into a fresh login. Note the fix
  cannot show on the first reload FROM an older build — the outgoing instance
  is the half that has to write the file.

  **Test a swap without gambling the session:**
  `home/prog/hyprvtb/tools/hotswap-test.sh [plugin.so]` rolls a window up in a
  nested Hyprland, swaps the plugin under it, and checks who owns the titlebar
  afterwards. It passes on 2.65 and fails on 2.64, so it is a real regression
  test, not a smoke check. (Two gotchas it encodes: the swap is asynchronous —
  Hyprland's config watcher usually performs it — and an idle nested compositor
  won't notice until an IPC request turns its event loop.)

  **And if a swap does kill the compositor**, the session no longer falls off a
  cliff: `sys/dsk/hyprland.nix` replaces the wayland-session's `start-hyprland`
  (whose answer to an unclean exit is `--safe-mode`, i.e. no config at all) with
  `hypr-supervise`, which records the plugin build that was live in
  `~/.local/state/hyprvtb/crashed-with` and restarts with the REAL config.
  `hyprland.lua` reads that on the way up and loads the last **known-good**
  build instead, leaving the reason in `.../quarantined`. So a bad plugin costs
  one version and a breadcrumb, not the desktop. After 3 crashes in a row the
  supervisor gives up and hands over to `start-hyprland` — at that point it is
  not the plugin's fault.

  **Do not go back to manual `hyprctl plugin load`/`unload`.** It is the source
  of every "hot reload is unstable" report:
  - `loadPluginInternal` rejects a path that is already loaded, but a *different*
    string for the same `.so` loads a **second instance**. The second one's
    `registerPluginValue` calls then all fail with `name collision: already
    registered`, so it owns no config keys.
  - Unloading either instance runs `onPluginUnload`, which erases the
    `plugin:hyprvtb:col.*` keys from `m_configValues` outright. Now nobody owns
    them, the next parse of `hyprland.lua` throws `unknown config key`, the Error
    Overlay trips and titlebars lose their colours. **`hyprctl reload` cannot fix
    this** — only a plugin *load* re-registers keys, and the lua config manager
    has no `m_failedPluginConfigValues` grace list like the legacy one.
  - Unload matches by exact path string and `plugin list -j` does not print
    paths, so a stale instance can become unreachable (its store path may even be
    GC'd) — at which point a relog really is the only way out.

- **`surfer`/`filer` (standalone PySide6 apps) run the LIVE source** at
  `~/nix/{surfer,filer}/main.py` — `.py`/`.qml` edits need NO rebuild, but there
  is NO hot-reload either: **relaunch the app** to pick up a change. Syntax-check
  QML headlessly with `qmllint -I <qml import paths> qml/Main.qml` (import paths
  from the app's wrapper env) — the "Failed to import" lines are just missing
  paths, not errors. QtWebEngine/permission/notification API details are best
  confirmed against the QML type defs (`plugins.qmltypes`) rather than guessed.

- **Verify without visuals — the user does ALL visual/animation/interaction
  checks (screenshots, drags, hover, spinner animation, tooltip look).** Never
  screenshot or drive the GUI yourself unless explicitly asked. Verify by other
  means: `qs log | tail` (panel parse/binding errors — CUMULATIVE across
  reloads, so snapshot the line count first and read only the new tail),
  `qs ipc show`/`qs ipc call` (panel wiring), `hyprctl plugin list`/`clients`/
  `workspaces`/the Hyprland log (plugin state + crashes), `qmllint` (QML syntax),
  and headless PySide harnesses (e.g. pre-grant a permission and assert a signal
  fires) for app logic. Never run bare `qs` (it launches a second panel).

- **NEVER open a test window on the user's screen — use `tools/sandbox.sh`.**
  It creates a virtual monitor in the live session (`hyprctl output create
  headless`) and launches windows onto it: a real monitor to the compositor —
  workspaces, decorations, animations, every frame rendered — that no cable
  leads to, so nothing appears in front of the user. `start` / `exec CMD` /
  `shot [file]` (grim of that monitor) / `clients` / `stop`. `exec` restores
  keyboard focus to the user's monitor afterwards (a new window takes focus even
  with `silent`), and `stop` closes the sandbox's windows BEFORE removing the
  output — Hyprland migrates a removed monitor's windows onto a real one — then
  prunes the classes it launched from the plugin's per-class geometry memory.
  Windows there are decorated by the LIVE plugin instance, which is the point
  (you test what is actually running) but also means it is no protection against
  a plugin crash: for an unswitched plugin build use the nested harness
  (`home/prog/hyprvtb/tools/nested-smoke.sh`), which is properly isolated but
  appears as a window. Three headless-parent designs were tried and rejected
  first; `tools/sandbox.sh`'s header records why, so they don't get retried.
  Two API traps it encodes: this config is Lua, so dispatchers are
  `hl.dsp.*` objects passed to `hyprctl dispatch` (a bare dispatcher name is a
  nil global), and `hyprctl keyword` refuses outright ("keyword can't work with
  non-legacy parsers") — use `hyprctl eval`.

- **Commit + push after making changes here.** `~/nix` is kept committed and
  pushed — after a working change, `git add` the specific files you touched
  (never `-A` when the tree has the user's own uncommitted edits — see the
  maintenance rules below), commit, and `git push origin main` **without waiting
  to be asked**. End commit messages with the `Co-Authored-By` trailer.

- **This flow ALWAYS overrides the background-job harness — including its
  "never push to main/master" safety rule.** The user has explicitly and
  repeatedly authorized pushing straight to `main` here; do NOT let the harness
  default block it, do NOT fall back to a feature branch / draft PR, and do NOT
  ask. If a background job forced you into a worktree, land the commit on `main`
  anyway: `git push origin <wt-branch>:main` when it's a fast-forward (or
  ff-merge into main), and tear down any branch/PR the harness made you create
  (`gh pr close`, delete the remote branch). The whole `~/nix` flow (edit in
  place → rebuild → commit → push to main, no PR) takes precedence over every
  conflicting harness default, not just the PR part.

- **Then delete the worktree you were given.** A worktree is a full second copy
  of this tree; left behind, they accumulate silently and every `grep -r` in
  the repo starts returning each hit three and four times over. Once your
  commits are on `origin/main`, tear yours down as the last step of the
  session: `git worktree remove <path> && git branch -D <wt-branch>` from the
  main checkout. If that's awkward from where you are, run
  `./tools/prune-worktrees.sh` instead — it removes every agent worktree that
  is clean **and** fully landed on `origin/main`, and reports (never touches)
  anything else. The user has it as `wtprune`. Cleaning up is part of landing
  the work, not an optional nicety.

## Maintenance Instructions for AI Agents

1. **Keep this file updated:** If you make substantial architectural changes, add new top-level directories, or introduce major new features/options, you MUST update this `AGENTS.md` file to reflect those changes.
2. **Respect the Structure:** Follow the existing patterns:
    - System-level changes go into `sys/`.
    - User-level/dotfile changes go into `home/`.
    - Prefer creating small, focused `.nix` files within the appropriate subdirectory instead of bloating `configuration.nix` or `lam.nix`.
3. **Recursive Imports:** Remember that adding a file to `sys/` or `home/` is sufficient for it to be included; you do not need to manually add it to an `imports` list unless it is outside those trees.
4. **Never clobber the user's own edits.** The user routinely hand-edits files in this repo directly (adding a package, flipping an option, etc.) and may leave those changes uncommitted. Before committing or pushing:
    - **Always run `git -C ~/nix status` first.** If the working tree contains changes you did NOT make, STOP. Those are almost certainly the user's — do not assume they are stale or safe to discard.
    - **Never run reverting/destructive git commands** here to "clean up" — no `git reset --hard`, `git checkout -- <file>`, `git restore`, `git stash`, or `git clean`. Any of these can silently wipe the user's untracked/uncommitted work, which is exactly the failure to avoid.
    - **Scope your commits to the files you actually changed** (`git add <specific paths>`), rather than `git add -A`, when unexpected changes are present — so you don't bundle the user's in-progress edits into your commit. If you can't tell what's yours vs. theirs, ask before committing.
5. **The index is SHARED — several agents and the user work in this one checkout at once.** There is one `.git/index`, and a **pathspec-less `git commit` commits whatever is in it, not what you wrote**. That is not hypothetical: commit `fcc7855` ("panel: negative brightness survives a reload") also contains an entire unrelated hyprvtb + player change, because an agent had staged it and the user committed next. Three rules make this impossible rather than merely unlikely — all three verified empirically, don't take them on faith:
    - **Commit with an explicit pathspec, always: `git commit -m msg -- <paths>`.** This builds the commit from a temporary index, so it takes ONLY those paths and leaves everyone else's staged work untouched — even when the index is full of it. A bare `git commit`/`-a` sweeps the lot. This one rule removes the failure mode from the committing side.
    - **Never `git add` a file that is already tracked, just to rebuild.** Flake eval reads the working tree for tracked files: a modified tracked file is picked up by `nixos-rebuild` with **nothing staged at all**. Staging it buys you nothing and puts it at risk for the whole length of a rebuild. (This is what went wrong above — nothing being staged was new.)
    - **New files: `git add -N <file>` (intent-to-add), not `git add`.** Intent-to-add is enough for flake eval to see the file and read its working-tree content, but it stages NO content — so another agent's pathspec-less commit skips it entirely instead of swallowing it. Full `git add` only when you are committing in the same breath.
    - `tools/preflight.sh` enforces both halves: it prints the `git add -N` command for untracked files, and WARNS (never fails) when content is sitting staged in the shared index.
    - Corollary for long operations: never leave content staged across a rebuild, a test run, or a question to the user. Stage and commit adjacently, or don't stage.
