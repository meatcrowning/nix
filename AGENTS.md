# NixOS Configuration Reference

This file provides a high-level overview of the configuration structure and key features for future reference and AI agents.

## Project Structure Overview

The configuration is split into three main areas: System-wide NixOS settings, User-specific Home Manager settings, and Machine-specific host definitions.

- `flake.nix`: The entry point for the entire configuration. Defines inputs (nixpkgs, home-manager, etc.) and orchestrates the `top` NixOS configuration.
- `hosts/`: Contains machine-specific configurations.
    - `hosts/top/`: Configuration for the primary host "top".
- `sys/`: System-wide NixOS modules and configurations.
    - Uses a recursive importer in `sys/default.nix` to automatically include all `.nix` files in this tree.
    - `sys/options.nix`: Defines custom options (e.g., `my.aerotheme.enable`).
    - `sys/dsk/`: Desktop environment configurations (Plasma, Hyprland).
- `home/`: Home Manager configuration for the user `lam`.
    - Also uses a recursive importer in `home/default.nix`.
    - `home/pkgs/`: Categories of packages (base, dev, game, media, etc.).
    - `home/prog/`: Program-specific configurations (zsh, bash, mpv, etc.).
- `lam.nix`: The entry point for the Home Manager configuration, which imports the `home/` directory.

## Key Features & Conventions

### Recursive Imports (`umport`)
Both `sys/` and `home/` use a helper function named `umport` (defined in their respective `default.nix` files). This function automatically imports every `.nix` file found recursively in those directories. Adding a new `.nix` file anywhere in these trees will automatically apply it to the configuration.

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

**Applying edits + reloading (READ THIS before editing panel/hypr config):**

- **Rebuild alias reality:** `rbhome`/`rbsys`/`update` all run
  `sudo nixos-rebuild switch --flake /home/lam/nix/#top` (home-manager is a
  NixOS module here; there is no standalone `home-manager switch`). A NOPASSWD
  rule allows the sudo. A **new** file must be `git add`-ed before the rebuild
  — the tree is dirty and flake eval ignores untracked files, so a brand-new
  `Foo.qml` is silently missing from the build otherwise.

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

- **Seed-once mutable files are NOT updated by rebuild:** `Theme.qml`,
  `hyprland.lua`, `hyprpaper.conf` are installed only if absent (they're
  rewritten in place at runtime by `wal-set.sh`). To change one, edit BOTH the
  nix source AND the live `~/.config/...` file **in place** (targeted string
  edit — never overwrite wholesale or you reset the live wal palette/border).
  Apply `hyprland.lua` keybind changes with **`hyprctl reload`** (re-runs the
  live Lua, re-registers `hl.bind`s, does not disturb the session).

- **Verify without visuals — the user does the visual/animation checks.** Don't
  screenshot. Use `qs log | tail` (parse/binding-loop errors), `qs ipc show` /
  `qs ipc call` (wiring), `hyprctl binds` (keybinds). `qs log` is CUMULATIVE
  across reloads — snapshot its line count before an action and read only the
  new tail, or old warnings will mislead you. Never run bare `qs` (it launches
  a second panel instance).

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
