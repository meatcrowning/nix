{ pkgs, ... }:

# `scrollbar-theme` — put this desktop's scrollbar into Vivaldi.
#
# Chromium never asks Qt or GTK for a scrollbar: it paints its own in Aura. So
# a page's bar is the one control `apps/qmlcommon/VScroll.qml` cannot reach,
# and in Vivaldi — somebody else's browser, no Stylus, no theme bridge — the
# only two seats are a Tampermonkey userscript for pages and Vivaldi's own
# `custom.css` for its UI. This command writes both, from
# `apps/pylib/scrollcss.py`: Oxygen's own bar in a Plasma session (measured off
# the real thing by `apps/pylib/tools/oxygen-scrollbar-probe.py`, since a web
# page cannot hand the painting to `QStyle`), the desktop's win31/beveled/flat
# variant otherwise.
#
# The userscript half is LIVE: it polls the same loopback courier the 4chan
# sheet does (`home/srvs/chan-theme.nix`, 127.0.0.1:8791/scrollbar.css) and
# re-adopts within 30s of a palette change. The `custom.css` half cannot poll —
# Vivaldi reads it at startup — so `chan-theme.nix`'s path unit rewrites it
# whenever the palette moves, which keeps it current for the next launch.
#
# Nothing has to be typed into Vivaldi: `vivaldi-theme --prefs` sets the
# Custom UI Modifications folder itself, as an ABSOLUTE path (Vivaldi hands that
# setting to the filesystem verbatim, so a `~` in it silently resolves to
# nothing and the sheet never loads). It must run with Vivaldi closed.
#
# Live source at apps/pylib/tools/scrollbar-userscript.py (absolute path, valid
# on both machines); a rebuild is only needed to change THIS wrapper.
{
  home.packages = [
    (pkgs.writeShellScriptBin "scrollbar-theme" ''
      exec ${pkgs.python3}/bin/python3 \
        /home/lam/nix/apps/pylib/tools/scrollbar-userscript.py "$@"
    '')
    # And the chrome around it: the colour ladder, Oxygen's relief and the same
    # scrollbar sheet, in the custom.css Vivaldi reads at startup, plus the
    # theme entry that makes Vivaldi's own light/dark classification agree.
    (pkgs.writeShellScriptBin "vivaldi-theme" ''
      exec ${pkgs.python3}/bin/python3 \
        /home/lam/nix/apps/pylib/tools/vivaldi-theme.py "$@"
    '')
  ];
}
