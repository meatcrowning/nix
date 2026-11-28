{ config, host, lib, pkgs, ... }:

let
  launcher = pkgs.callPackage ../../apps/df-launcher/package.nix { };
  x86 = if host == "air" then import pkgs.path {
    system = "x86_64-linux";
    config.allowUnfree = true;
  } else pkgs;
  # DF runs as x86_64 on both hosts, including inside book's microVM.
  ambience = x86.stdenv.mkDerivation {
    pname = "df-ambience";
    version = "53.17";
    src = ../../apps/df-launcher/ambience.c;
    dontUnpack = true;
    buildPhase = ''
      "$CC" -shared -fPIC -O2 -Wall -Wextra -Werror "$src" -o ambience.so -ldl
    '';
    installPhase = ''
      install -Dm755 ambience.so "$out/lib/ambience.so"
    '';
  };
  launchGame = pkgs.writeShellScript "df-direct-game" ''
    set -eu
    cd "$1"
    common=$(dirname "$PWD")
    exec "$HOME/.local/share/df-launcher/capture" --direct \
      ${x86.steam.run}/bin/steam-run \
      "$common/SteamLinuxRuntime_soldier/_v2-entry-point" --verb=waitforexitandrun -- \
      "$common/SteamLinuxRuntime/scout-on-soldier-entry-point-v2" -- \
      "$PWD/dwarfort" --nosteam-dfhack
  '';
  direct = pkgs.writeShellScriptBin "df-launcher-direct" ''
    exec ${lib.optionalString (host == "air") "/run/current-system/sw/bin/df-game-runtime "}${launchGame} "$@"
  '';
in
{
  home.packages = [ launcher direct ];

  # Steam's runtime sees the home directory. Keep a standalone copy there
  # so the Steam launch option stays stable across system generations.
  home.activation.installDfCapture = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    capture_dir=${lib.escapeShellArg "${config.home.homeDirectory}/.local/share/df-launcher"}
    run mkdir -p -m 700 "$capture_dir"
    if ! cmp -s "${launcher}/bin/df-launcher-capture" "$capture_dir/capture"; then
      run install -m 755 "${launcher}/bin/df-launcher-capture" "$capture_dir/capture.new"
      run mv -T "$capture_dir/capture.new" "$capture_dir/capture"
    fi
    if ! cmp -s "${ambience}/lib/ambience.so" "$capture_dir/ambience.so"; then
      run install -m 755 "${ambience}/lib/ambience.so" "$capture_dir/ambience.so.new"
      run mv -T "$capture_dir/ambience.so.new" "$capture_dir/ambience.so"
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
