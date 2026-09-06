{ pkgs, ... }:

# Generate Vivaldi's Tampermonkey theme userscript from live, Qt-free source.
# The installed script polls the loopback courier at 127.0.0.1:8791, so rerun
# this only when the sheet or generator changes, not after palette/wallpaper
# changes. Its HTTP update URL is installed through Tampermonkey's
# Utilities > Install from URL; direct navigation is intercepted incorrectly.
{
  home.packages = [
    (pkgs.writeShellScriptBin "chan-theme" ''
      exec ${pkgs.python3}/bin/python3 \
        /home/lam/nix/apps/pylib/tools/chan-userscript.py "$@"
    '')
  ];
}
