{ lib, ... }:
{
  # Every BESPOKE program seal installed into the hicolor icon theme, listed by
  # icon NAME — the `Icon=` its desktop entry carries, and the name the icon
  # theme (and Quickshell's icon provider) resolves.
  #
  # The seals are `currentColor` sigils: the sigil IS the theme's foreground
  # (docs/DESIGN.md §3.1), not a baked hue. So every surface that draws one has
  # to paint it — hyprvtb's titlebar through a librsvg stylesheet, goetia's
  # window icon through textual substitution, and the panel through
  # AppIcon.qml, which has only the icon's NAME to go on: `Quickshell.iconPath`
  # hands back an `image://icon/<name>` URL, never a file path, so "is this one
  # of ours" cannot be answered by looking at where the file lives. This list is
  # that answer, and `home/prog/quickshell.nix` generates AppSeals.qml from it.
  #
  # Declare a seal next to the `home.file` that installs it. One left out draws
  # in the file's baked fallback colour (#cc4400, red) wherever Qt renders it
  # raw, on every wallpaper.
  options.my.appSeals = lib.mkOption {
    type = lib.types.listOf lib.types.str;
    default = [ ];
    example = [ "player" ];
    description = "Icon names of the bespoke app seals installed into hicolor.";
  };
}
