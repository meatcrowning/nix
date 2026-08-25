{ lib, host, ... }:

# The Plasma colour scheme, on book: OxygenDark with the UNFOCUSED palette baked
# in as the only palette.
#
# OxygenDark distinguishes an unfocused window by a KColorScheme *effect* rather
# than by a second set of colours — `[ColorEffects:Inactive]` ColorEffect=1
# (desaturate) at ColorAmount=-0.9, which is `KColorUtils::darken(c, 0.0, 1.9)`:
# luma untouched, chroma multiplied by 1.9. Hence the brighter, bluer unfocused
# window. He wants that colour on EVERY window (2026-08-24), and there is no
# `[ColorEffects:Active]` to answer it with — so `plasma-files/OxygenDarkFlat.colors`
# carries every Background*/Decoration* already put through that chroma x1.9 and
# turns the inactive effect off. Foreground* stay at their active values: the
# effect's other half (ContrastEffect=2 at 0.25) faded text toward the
# background, which is the greying he asked to lose, and `[WM]` is white on both
# states so the titlebar title reads the same white as the window's body text.
#
# book only, like the Oxygen look-and-feel it derives from (home/plasma.nix):
# top's Plasma session is stock Breeze or the aerotheme one. The scheme FILE is
# installed on both hosts — it is inert until something picks it, and that is
# the same call home/prog/oxygen.nix makes about oxygenrc.
#
# plasma-manager applies this with `plasma-apply-colorscheme` from its one-shot
# login script, ordered after the `plasma-apply-lookandfeel` that would
# otherwise put OxygenDark back.
{
  home.file.".local/share/color-schemes/OxygenDarkFlat.colors".source =
    ./plasma-files/OxygenDarkFlat.colors;

  programs.plasma.workspace.colorScheme = lib.mkIf (host == "air") "OxygenDarkFlat";
}
