{ ... }:

# "KWin activated your window" — as a D-Bus call to the window's own process.
#
# The whole argument is in kwin-winactive-files/contents/code/main.js and in
# apps/pylib/kwinactive.py: KWin's decoration and a Qt client work their focus
# out from different facts, a screenshot tool splits the two, and the window
# comes out drawn in two colour groups at once. There is no Wayland route to
# close it — KWin keeps `org_kde_plasma_window_management` for plasmashell — so
# the compositor pushes instead of the app pulling.
#
# Plasma only. The Hyprland session draws its own titlebars (hyprvtb), where
# both halves already read one focus state.

{
  home.file = {
    ".local/share/kwin/scripts/winactive/metadata.json".source =
      ./kwin-winactive-files/metadata.json;
    ".local/share/kwin/scripts/winactive/contents/code/main.js".source =
      ./kwin-winactive-files/contents/code/main.js;
  };

  # The Id in metadata.json plus "Enabled" — how KWin turns a script on.
  programs.plasma.configFile.kwinrc.Plugins.winactiveEnabled = true;
}
