{ ... }:

# The application launcher's circle, in ink rather than white.
#
# The Kickoff applet is configured with `icon=draw-circle`, which is an ICON
# THEME name, not a Plasma-theme SVG — so it is never recoloured by the panel's
# colour group. The active icon theme (`oxygen`) is not installed, so the name
# falls through to the Yaru themes under ~/.local/share/icons, whose copy bakes
# `.ColorScheme-Text { color:#e1e1e1 }` — near-white, which read fine on a dark
# panel and not at all on a light one.
#
# Rather than override `draw-circle` (which would mean shadowing a whole icon
# theme and changing every other icon with it), this ships a separate name the
# applet points at. Set on the applet with:
#   qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
#     'panels().forEach(p => p.widgets().forEach(w => { if (w.type ==
#      "org.kde.plasma.kickoff") { w.currentConfigGroup = ["General"];
#      w.writeConfig("icon", "launcher-circle"); w.reloadConfig(); } }))'
{
  home.file.".local/share/icons/hicolor/scalable/actions/launcher-circle.svg".source =
    ./app-icons/launcher-circle.svg;
}
