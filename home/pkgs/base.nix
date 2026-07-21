{ pkgs, lib, host, ... }:

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
    # open-webui hardcodes KEY_FILE = cwd/.webui_secret_key, so launching it
    # from $HOME litters ~/.webui_secret_key. Setting WEBUI_SECRET_KEY makes
    # upstream skip that file entirely; this wrapper keeps the secret in a
    # stable spot under ~/.local/share/open-webui instead.
    (writeShellScriptBin "open-webui" ''
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
      exec ${open-webui}/bin/open-webui "$@"
    '')
    claude-code

    #kde-material-you-colors-latest
    #ventoy-full-qt
    #kquitapp6
    #okay maybe a little media
  # already native on air (this Fedora install) — skip duplicating there.
  ] ++ lib.optionals (host != "air") [
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
  ];
}
