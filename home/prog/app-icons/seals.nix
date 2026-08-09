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
  #
  # REDRAWING an existing seal (same icon name, new artwork) does NOT show up in
  # the panel from `sudo rebuild-top` alone, AND — measured 2026-08-09 — the
  # in-place `Theme.qml` reload does NOT fix it either. Qt's global QIconLoader
  # caches every icon by NAME for the whole process's lifetime; it never re-reads
  # a changed file behind the same name, and a Quickshell config reload runs in
  # the SAME process, so the panel keeps serving the old, already-rendered glyph.
  # (An earlier note here claimed the reload was the remedy; it is not — that is
  # what left the redrawn Zagan/updater seal stale in the running bar.) The only
  # thing that clears it is a fresh panel PROCESS:
  #
  #   systemctl --user restart quickshell-panel.service   # flushes the icon cache
  #
  # (or a next login). The wallpaper + bars flash once and the service's
  # Restart=always brings them straight back; carried PersistentProperties state
  # is lost across a restart (it survives a reload, not a process swap). The
  # `Theme.qml` bump reload still applies for panel QML/logic edits — it is only
  # a REDRAWN seal, resolved through QIconLoader by name, that it cannot refresh.
  options.my.appSeals = lib.mkOption {
    type = lib.types.listOf lib.types.str;
    default = [ ];
    example = [ "player" ];
    description = "Icon names of the bespoke app seals installed into hicolor.";
  };
}
