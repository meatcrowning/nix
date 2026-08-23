{ pkgs, ... }:

# `chan-theme` — regenerate the Tampermonkey userscript that puts this
# desktop's look on 4chan in Vivaldi.
#
# surfer wears the same sheet natively, through its own `surferonee://` courier
# (live, no regeneration). Vivaldi is somebody else's browser: no Stylus, and
# the only injection seat is Tampermonkey — where OneeChan already lives — so
# the CSS goes into a userscript. This is the command that writes it.
#
# Writing it is no longer the same as keeping it current: since 2026-08-23 the
# script POLLS `home/srvs/chan-theme.nix`'s loopback courier
# (127.0.0.1:8791, `apps/pylib/tools/chan-theme-server.py`) and re-adopts the
# sheet whenever the palette moves, open tab included. The embedded copy is
# only the fallback for a page loaded while that unit is down. So re-run this
# when the SHEET (`apps/pylib/chantheme.py`) or the generator changes — NOT
# after a colour-scheme or wallpaper change, which now needs nothing.
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
