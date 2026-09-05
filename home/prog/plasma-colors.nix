{ lib, ... }:

# The Plasma colour schemes on both hosts: dynamic light and dark Oxygen
# palettes, each with the UNFOCUSED palette baked in as the only palette.
#
# OxygenDark distinguishes an unfocused window by a KColorScheme *effect* rather
# than by a second set of colours — `[ColorEffects:Inactive]` ColorEffect=1
# (desaturate) at ColorAmount=-0.9, which is `KColorUtils::darken(c, 0.0, 1.9)`:
# luma untouched, chroma multiplied by 1.9. Hence the brighter, bluer unfocused
# window. He wants that colour on EVERY window (2026-08-24), and there is no
# `[ColorEffects:Active]` to answer it with — so both templates turn the
# inactive effect off. OxygenDarkFlat carries every Background*/Decoration*
# already put through that chroma x1.9; OxygenLightFlat retains Oxygen's light
# surfaces. Foreground* stay at their active values: the
# effect's other half (ContrastEffect=2 at 0.25) faded text toward the
# background, which is the greying he asked to lose, and `[WM]` is white on both
# states so the titlebar title reads the same white as the window's body text.
#
# The Oxygen look-and-feel itself remains book-only (home/plasma.nix), but the
# colour result is desktop-wide: top was still selecting raw OxygenDark, so its
# unfocused windows were brighter than its focused ones after book had already
# been flattened. Both hosts select this scheme now.
#
# plasma-manager applies this with `plasma-apply-colorscheme` from its one-shot
# login script, ordered after the `plasma-apply-lookandfeel` that would
# otherwise put OxygenDark back.
#
# THE FILE THIS INSTALLS IS A TEMPLATE, NOT THE LIVE SCHEME (2026-08-24). The
# live `~/.local/share/color-schemes/{OxygenDarkFlat,OxygenLightFlat}.colors`
# are MINTED from them by `wal-set.sh` -> `plasma-scheme.py`, with the whole blue
# family hue-rotated onto the wallpaper's accent. They appear in System Settings
# → Colors: selecting either persists as the user's choice and wallpaper changes
# repaint that selected version. They cannot be
# `/nix/store` symlink for the same reason `Theme.qml` and `hyprland.lua`
# cannot: something at runtime writes it. The seed below is what a machine that
# has never run wal-set.sh reads — the untinted Oxygen blues.
{
  xdg.configFile."scripts/plasma-scheme-template.colors".source =
    ./plasma-files/OxygenDarkFlat.colors;
  xdg.configFile."scripts/plasma-light-scheme-template.colors".source =
    ./plasma-files/OxygenLightFlat.colors;

  # Seed the live scheme once, so plasma-manager's login `plasma-apply-colorscheme`
  # has a file to read before the first wallpaper apply. Never overwrites a
  # minted one — wal-set.sh owns it from then on.
  home.activation.seedPlasmaScheme = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    for scheme in OxygenDarkFlat OxygenLightFlat; do
      live="$HOME/.local/share/color-schemes/$scheme.colors"
      if [ -L "$live" ]; then rm -f "$live"; fi   # retire old store symlinks
      if [ ! -e "$live" ]; then
        case "$scheme" in
          OxygenDarkFlat) source=${./plasma-files/OxygenDarkFlat.colors} ;;
          OxygenLightFlat) source=${./plasma-files/OxygenLightFlat.colors} ;;
        esac
        $DRY_RUN_CMD install -D -m644 "$source" "$live"
      fi
    done
  '';

  programs.plasma.workspace.colorScheme = "OxygenDarkFlat";
}
