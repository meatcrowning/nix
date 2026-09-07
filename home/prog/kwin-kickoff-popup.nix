{ ... }:

# Kickoff is anchored to its panel button. With panels on both the top and
# left edges, that puts its Meta-key popup over the left panel. KWin sees the
# popup as a normal Plasma popup surface, so the companion script moves only
# that top-left surface into the usable desktop while leaving the button put.
{
  home.file = {
    ".local/share/kwin/scripts/kickoffpopup/metadata.json".source =
      ./kwin-kickoff-popup-files/metadata.json;
    ".local/share/kwin/scripts/kickoffpopup/contents/code/main.js".source =
      ./kwin-kickoff-popup-files/contents/code/main.js;
  };

  programs.plasma.configFile.kwinrc.Plugins.kickoffpopupEnabled = true;
}
