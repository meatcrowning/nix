{ pkgs, config, ... }:

# `utilities-terminal` is Oxygen's own terminal icon. Keeping the desktop entry
# on that icon-theme name lets the launcher follow the active Oxygen palette on
# both hosts instead of freezing a one-off bitmap or SVG beside the entry.
{
  home.packages = [
    (pkgs.writeShellScriptBin "codex-theme-reload" ''
      exec ${pkgs.python3}/bin/python3 /home/lam/nix/apps/pylib/tools/codex-theme-reload.py "$@"
    '')
  ];

  # A palette write queues refreshes for supervised Codex windows.  The
  # supervisor waits for Codex's own task_complete event before restarting the
  # TUI, so a running agent is never interrupted.
  systemd.user.services.codex-theme-reload = {
    Unit = {
      Description = "queue Codex refresh after a desktop theme change";
      # KConfig and the wallpaper writer update both watched files in a burst.
      # Every invocation merely replaces one queue generation, so limiting
      # those harmless coalescing writes can only lose the requested refresh.
      StartLimitIntervalSec = 0;
    };
    Service = {
      Type = "oneshot";
      Environment = [ "PATH=${config.home.profileDirectory}/bin:/run/current-system/sw/bin:/usr/bin:/bin" ];
      ExecStart = "${config.home.profileDirectory}/bin/codex-theme-reload queue";
    };
  };
  systemd.user.paths.codex-theme-reload = {
    Unit.Description = "queue a Codex refresh when the Plasma palette changes";
    Path = {
      PathChanged = [ "%h/.config/kdeglobals" "%h/.config/quickshell/Theme.qml" ];
      PathModified = [ "%h/.config/kdeglobals" "%h/.config/quickshell/Theme.qml" ];
    };
    Install.WantedBy = [ "default.target" ];
  };

  home.file.".local/share/applications/codex.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=codex
    GenericName=codex
    Comment=start codex in the nix checkout
    Exec=${config.home.profileDirectory}/bin/konsole --workdir /home/lam/nix -e ${config.home.profileDirectory}/bin/codex-theme-reload supervise -- codex
    Icon=utilities-terminal
    Terminal=false
    Categories=Development;Utility;
    Keywords=codex;openai;agent;nix;
  '';
}
