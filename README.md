<img width="1920" height="1080" alt="desk2" src="https://github.com/user-attachments/assets/f5c81e56-bcef-43bc-97a0-0f004572a3bb" />
<img width="1920" height="1080" alt="desk3" src="https://github.com/user-attachments/assets/62c10bfa-8f30-4ab4-8249-b09676932dfb" />
<img width="1920" height="1080" alt="desk" src="https://github.com/user-attachments/assets/eb01f771-96bb-4b54-8b79-5e6cbcf35c07" />

# `nixos flake`

after a certain point i felt that my conversation with nixos should be mediated by language models. initially, this was via `aider` utilizing a multitude of models in a multitude of roles. and then grew into a sort of black hole from which various model and various harnesses have come to visit. im only now looping in git - because there is now a c++ plugin which add vertical titlebars. fun. the rest of this readme consists of words that i have neither written nor read (in great detail).  

## What it is

- **One host, two build targets.** `flake.nix` exposes
  `nixosConfigurations.top` (the whole system) and `homeConfigurations.lam`
  (just my user env), so the machine can be rebuilt as a unit or my dotfiles
  updated on their own.
- **Tracks `nixos-unstable`** with home-manager `release-25.11`, `allowUnfree`,
  on `x86_64-linux`.
- **The hardware:** AMD Ryzen 7 9800X3D, 30 GiB RAM, NVIDIA RTX 5070 on the
  proprietary driver (`nvidia.open = true`) — see `sys/hw/nvidia.nix`.
- **A desktop in transition.** The default session is **KDE Plasma 6**
  (`sys/dsk/plasma.nix`), optionally reskinned as Windows Aero via the
  `aerothemeplasma-nix` input (toggle: `my.aerotheme.enable`). Alongside it,
  a hand-built **Hyprland + Quickshell** desktop is being stood up
  (`sys/dsk/hyprland.nix`, `home/prog/hyprland.nix`, `home/prog/quickshell-files/`).
- **Some custom pieces worth knowing about:**
  - `home/prog/hyprvtb/` — `hyprvtb`, a compositor-side C++ Hyprland plugin
    that draws vertical per-window titlebars (packaged in `hyprvtb.nix`).
  - `home/prog/quickshell-files/` — the QML for the Quickshell bar, launcher,
    notifications, lock screen, OSD, etc.
  - `home/srvs/wal-files/` — pywal-driven theming (`wal-set.sh` rewrites
    palettes across Quickshell, kitty, and the hyprvtb plugin on wallpaper
    change).
  - Overlays in `flake.nix` for a CUDA build of `ollama` and a `vcv-rack`
    segfault-patch removal.

## How it came to be

The machine was first installed from a simple, Plasma-only bootstrap config
that still lives (stale) at `/etc/nixos`. This flake is the successor: the
config was reorganized into a standalone, recursively-imported tree under
`~/nix`, which has since diverged well past that original — adding the
Hyprland/Quickshell modules, plasma-manager, the custom overlays, and the
`hyprvtb` plugin. It was put under git on 2026-07-18 and pushed to a private
repo.

Part of the ongoing work is a migration: the Hyprland/Quickshell side started
as hand-authored dotfiles from a previous Fedora Asahi (aarch64) laptop, now
being ported onto this box and expressed in Nix. That's why Plasma and
Hyprland currently coexist here — Plasma is the working daily driver while the
Hyprland desktop is built out.

## Layout

```
flake.nix          inputs + the `top` system and `lam` home outputs
lam.nix            home-manager entry point (imports home/)
hosts/top/         machine-specific: configuration.nix, hardware-configuration.nix
sys/               system-wide NixOS modules (auto-imported via umport)
  dsk/  plasma.nix, hyprland.nix      desktop sessions
  hw/   nvidia.nix                    graphics/hardware
  gme/  steam.nix                     gaming
  options.nix                         custom `my.*` options (e.g. aerotheme)
home/              home-manager modules (auto-imported via umport)
  pkgs/            package sets: base, dev, game, media, desktop
  prog/            per-program config: zsh, kitty, mpv, qutebrowser,
                   hyprland, quickshell, hyprvtb, slskd, …
  srvs/            user services: pywal, easyeffects, udiskie
```

Both `sys/` and `home/` use a recursive importer (`umport`, defined in each
`default.nix`): **dropping a `.nix` file anywhere in those trees is enough to
include it** — no manual `imports` list. See `AGENTS.md` for the deeper
conventions (the umport mechanism, the aerotheme toggle, the seeded-mutable
theme files, and the hyprvtb plugin lifecycle).

## Building

Rebuild aliases (defined in `home/prog/zsh.nix`):

| alias    | command                                                        |
|----------|----------------------------------------------------------------|
| `rbsys`  | `sudo nixos-rebuild switch --flake ~/nix#top`                  |
| `rbhome` | `home-manager switch --flake ~/nix#lam`                        |
| `update` | `rbsys` plus `--upgrade` (bumps flake inputs)                  |

> **Gotcha:** this is a git-backed flake, so a rebuild only sees
> **git-tracked** files. `git add` any *new* file before switching, or the
> build silently omits it.
