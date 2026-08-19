{ ... }:

# "Roll up window" for the Plasma session, as a KWin script.
#
# KWin dropped window shading upstream — no shade operation in libkwin, no
# Shade button in the decoration KCM, no Shade titlebar mouse command — so
# there is nothing to re-enable and no way to put it back on the titlebar (the
# decoration button set is a fixed KDecoration enum). This re-implements the
# behaviour by resizing the frame down to its top border, on a global shortcut.
# Rationale and limits: kwin-rollup-files/contents/code/main.js.
#
# Meta+R matches the hyprvtb rollup keybind in the Hyprland session
# (home/prog/hypr-files/hyprland.lua).

{
  home.file = {
    ".local/share/kwin/scripts/rollupwindow/metadata.json".source =
      ./kwin-rollup-files/metadata.json;
    ".local/share/kwin/scripts/rollupwindow/contents/code/main.js".source =
      ./kwin-rollup-files/contents/code/main.js;
  };

  # The Id in metadata.json plus "Enabled" — how KWin turns a script on.
  programs.plasma.configFile.kwinrc.Plugins.rollupwindowEnabled = true;
}
