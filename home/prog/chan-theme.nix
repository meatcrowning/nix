{ pkgs, ... }:

# `chan-theme` — regenerate the Tampermonkey userscript that puts this
# desktop's look on 4chan in Vivaldi.
#
# surfer wears the same sheet natively, through its own `surferonee://` courier
# (live, no regeneration). Vivaldi is somebody else's browser: no Stylus, and
# the only injection seat is Tampermonkey — where OneeChan already lives — so
# the CSS has to be BAKED into a userscript, and therefore re-baked whenever
# the colour scheme or the wallpaper moves. This is that command.
#
# Live source at apps/pylib/tools/chan-userscript.py (absolute path, valid on
# both machines); a rebuild is only needed to change THIS wrapper. Plain
# python3 — the generator is deliberately Qt-free, which is also why the sheet
# lives in pylib/chantheme.py rather than inside surfer.
{
  home.packages = [
    (pkgs.writeShellScriptBin "chan-theme" ''
      exec ${pkgs.python3}/bin/python3 \
        /home/lam/nix/apps/pylib/tools/chan-userscript.py "$@"
    '')
  ];
}
