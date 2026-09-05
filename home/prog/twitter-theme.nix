{ pkgs, ... }:

# The Tampermonkey installer for the live Twitter/X page sheet.  Once installed,
# it polls chan-theme's loopback courier and follows wallpaper/KDE changes in an
# already-open tab; this command is only needed after the script itself changes.
{
  home.packages = [
    (pkgs.writeShellScriptBin "twitter-theme" ''
      exec ${pkgs.python3}/bin/python3 /home/lam/nix/apps/pylib/tools/twitter-userscript.py "$@"
    '')
  ];
}
