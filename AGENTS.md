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

## Maintenance Instructions for AI Agents

1. **Keep this file updated:** If you make substantial architectural changes, add new top-level directories, or introduce major new features/options, you MUST update this `REFERENCE.md` file to reflect those changes.
2. **Respect the Structure:** Follow the existing patterns:
    - System-level changes go into `sys/`.
    - User-level/dotfile changes go into `home/`.
    - Prefer creating small, focused `.nix` files within the appropriate subdirectory instead of bloating `configuration.nix` or `lam.nix`.
3. **Recursive Imports:** Remember that adding a file to `sys/` or `home/` is sufficient for it to be included; you do not need to manually add it to an `imports` list unless it is outside those trees.
