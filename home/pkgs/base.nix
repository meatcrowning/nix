{ pkgs, lib, host, inputs, ... }:

{
  home.packages = with pkgs; [
    vim
    nh
    wget
    htop
    broot
    croc
    home-manager
    cava
    killall
    inputs.llm-agents.packages.${pkgs.stdenv.hostPlatform.system}.codex
    inputs.llm-agents.packages.${pkgs.stdenv.hostPlatform.system}.claude-code
    #kde-material-you-colors-latest
    #ventoy-full-qt
    #kquitapp6

    btop
    tree
    unzip
    git
    gh
    curl
    rsync
    fastfetch
    cmatrix
    libnotify
    feh
    playerctl
    smartmontools
    usbutils
    btrfs-progs
    ranger
    grim
  ]

   # gated
   ++ lib.optional pkgs.stdenv.hostPlatform.isx86_64 (writeShellScriptBin "open-webui" ''
    set -eu
    keydir="''${XDG_DATA_HOME:-$HOME/.local/share}/open-webui"
    keyfile="$keydir/.webui_secret_key"
    if [ -z "''${WEBUI_SECRET_KEY:-}" ]; then
      if [ ! -f "$keyfile" ]; then
        mkdir -p "$keydir"
        head -c 24 /dev/urandom | base64 > "$keyfile"
      fi
      export WEBUI_SECRET_KEY="$(cat "$keyfile")"
    fi
    exec ${pkgs.open-webui}/bin/open-webui "$@"
  '')

  ++ lib.optional pkgs.stdenv.hostPlatform.isx86_64
     inputs.llm-agents.packages.${pkgs.stdenv.hostPlatform.system}.hermes-agent;
}
