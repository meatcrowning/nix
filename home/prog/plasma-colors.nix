{ lib, ... }:

# Both hosts select flattened Oxygen palettes: inactive effects are disabled and
# their desired colors are baked into the templates. Plasma Manager applies the
# scheme after look-and-feel.
#
# These are templates, not live files. wal-set.sh/plasma-scheme.py mint writable
# wallpaper-tinted copies under ~/.local/share/color-schemes; activation only
# seeds a missing copy and must never replace an existing minted one.
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
