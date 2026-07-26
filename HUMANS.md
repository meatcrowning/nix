# HUMANS.md

> **disclaimer:** none of this file has been read by me. it was written by a
> machine, and i have not checked that it's accurate or that it reads nicely.
> i promise i'll get around to it soon.

`AGENTS.md` is the manual the AI agents work from. this one is the same idea
pointed at people.

## recreating this setup

the short version, if you want to run this (or steal pieces of it):

- **clone to `/home/lam/nix` — the path is load-bearing.** the sudo rebuild
  wrapper, the live-source app wrappers (everything under `apps/` —
  filer/viewer/player/painter/surfer — runs `main.py` straight out of this
  checkout), and several out-of-store symlinks all hardcode it. different
  username = grep for `/home/lam` first.
- **replace `hosts/top/hardware-configuration.nix`** with your machine's own
  (`nixos-generate-config`), then first build:
  `sudo nixos-rebuild switch --flake /home/lam/nix#top`. after that the config
  installs `rebuild-top` + the `rbsys`/`rbhome`/`update` aliases and rebuilds
  are passwordless. `tools/preflight.sh` sanity-checks a change without root.
- **private pieces degrade gracefully** — you don't have access to them and
  that's fine: `sounds/` (a private submodule of Windows Vista event sounds;
  clone without `--recurse-submodules` and you just get silence), `docs/` (my
  private working notes, gitignored here), and the claude-memory sync (skips
  itself without auth to its private repo).
- **runtime secrets are never in this repo**: slskd expects an api key at
  `~/.secrets/slskd-api-key` (0600). no key, no slskd — everything else runs.
- **hardcoded media paths** you'll want to change or ignore: music library at
  `/run/media/lam/SSD/aud`, image-gen models at `/home/lam/models`, wallpapers
  drop-folder at `~/Pictures/wall`.
- **macbook / asahi**: no nixos needed — `home-manager switch --flake ~/nix#air`
  layers the same `home/` tree onto Fedora Asahi (aarch64). `sys/` is
  nixos-only and simply doesn't apply there.
- **`AGENTS.md` is the real manual** — structure, conventions, reload
  procedures, and every sharp edge, written for AI agents but just as useful
  for humans.
