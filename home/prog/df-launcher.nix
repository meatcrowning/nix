{ config, lib, pkgs, ... }:

let
  launcher = pkgs.callPackage ../../apps/df-launcher/package.nix { };
in
{
  home.packages = [ launcher ];

  # Steam's runtime sees the home directory. Keep a standalone copy there
  # so the Steam launch option stays stable across system generations.
  home.activation.installDfCapture = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    capture_dir=${lib.escapeShellArg "${config.home.homeDirectory}/.local/share/df-launcher"}
    run mkdir -p -m 700 "$capture_dir"
    if ! cmp -s "${launcher}/bin/df-launcher-capture" "$capture_dir/capture"; then
      run install -m 755 "${launcher}/bin/df-launcher-capture" "$capture_dir/capture.new"
      run mv -T "$capture_dir/capture.new" "$capture_dir/capture"
    fi
  '';

  xdg.desktopEntries.df-launcher = {
    name = "Dwarf Fortress Launcher";
    exec = "${launcher}/bin/df-launcher";
    icon = "applications-games";
    categories = [ "Game" ];
    terminal = false;
  };
}
