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
    # claude-code, off numtide/llm-agents.nix instead of nixpkgs so it tracks
    # Anthropic's releases (nixpkgs' copy lags days behind). system is derived
    # from pkgs so this resolves on both `top` (x86_64) and `air` (aarch64).
    inputs.llm-agents.packages.${pkgs.stdenv.hostPlatform.system}.claude-code
    # No built-in way to prune old Claude Code sessions (~/.claude/projects/*.jsonl)
    # or finished background agents (~/.claude/jobs/*); this adds an interactive
    # `claude-sessions` picker (sessions | tasks | restore | empty-trash) that
    # trashes rather than hard-deletes. readFile keeps the bash verbatim so its
    # ${...} expansions need no nix escaping.
    (writeShellScriptBin "claude-sessions" (builtins.readFile ./claude-sessions.sh))

    #kde-material-you-colors-latest
    #ventoy-full-qt
    #kquitapp6
    #okay maybe a little media

    # These used to be gated off `air` to avoid duplicating Fedora's copies,
    # but there's no real reason to keep the CLI layer on dnf — let nix own it
    # on both hosts. The dnf copies stay installed (many are pulled in as KDE/
    # Asahi metapackage deps and can't cleanly `dnf remove`) but nix wins on
    # PATH. GUI/GPU apps stay on Fedora — nixpkgs' Mesa lacks Asahi (Honeykrisp)
    # support, so those render in software here.
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
  # open-webui is a heavy python+node build with no aarch64 binary cache, and it
  # fails to build under Asahi — gate it to x86_64 (like google-chrome) so it
  # doesn't block `air`'s whole home-manager generation. `top` still gets it.
  # The wrapper exists because open-webui hardcodes KEY_FILE = cwd/.webui_secret_key,
  # so launching it from $HOME litters ~/.webui_secret_key. Setting WEBUI_SECRET_KEY
  # makes upstream skip that file; this keeps the secret under ~/.local/share/open-webui.
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
  # hermes-agent, off the same numtide/llm-agents.nix that supplies claude-code
  # — a prebuilt binary with no aarch64 build in the flake's `available` filter,
  # so it is gated to x86_64 the way open-webui is and lands on `top` only
  # (`air`/book is aarch64 and misses it).
  #
  # It used to carry our own hermes-agent-python314.patch: upstream's
  # tools/daemon_pool.py mirrored the 3.8–3.13 ThreadPoolExecutor internals
  # (_initializer/_initargs), which 3.14 removed in favour of a per-instance
  # worker context, so reaching for them raised AttributeError and silently
  # killed every tool/agent call that ran through the pool. As of the
  # 2026-08-20 `nix flake update llm-agents` the input applies its OWN
  # daemon-pool-python314.patch, and ours then failed to apply on top of it —
  # so it is gone, and this is the plain package again.
  ++ lib.optional pkgs.stdenv.hostPlatform.isx86_64
     inputs.llm-agents.packages.${pkgs.stdenv.hostPlatform.system}.hermes-agent;
}
