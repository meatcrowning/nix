{ ... }:

# Plasma 6 stores manual-tile layouts per virtual desktop and output UUID in
# kwinrc. UUIDs are intentionally host-local, so they cannot be declared as a
# static configFile entry. KWin's stock layout is three columns; this script
# recognises only that untouched default and replaces it with two rows of three
# equal tiles. KWin then saves the resulting per-output layout itself.
{
  home.file = {
    ".local/share/kwin/scripts/six-tile-grid/metadata.json".source =
      ./kwin-six-tile-grid-files/metadata.json;
    ".local/share/kwin/scripts/six-tile-grid/contents/code/main.js".source =
      ./kwin-six-tile-grid-files/contents/code/main.js;
  };

  programs.plasma.configFile.kwinrc.Plugins.six-tile-gridEnabled = true;
}
