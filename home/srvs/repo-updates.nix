{ pkgs, lib, config, ... }:

# "The other machine pushed" — as a toast with buttons.
#
# `~/nix` is the bit that does not sync itself: pulling the flake is only half
# of landing it, the other half is a switch on the machine you are sitting at.
# This daemon keeps that decision reachable and delegates the logic to
# `repo-updates-files/repo-updates.py`.
#
# It watches `origin/main`, classifies the cost of applying it, and keeps one
# persistent toast up while the user decides. The host branch stays inside the
# script (`sudo rebuild-top` vs `rebuild-air`); everything else is shared.
#
# It has to be a daemon because `notify-send -w` must stay alive for the button
# press that closes the toast. `nix-pull` is the no-toast entry point.

{
  xdg.configFile."scripts/repo-updates.py" = {
    source = ./repo-updates-files/repo-updates.py;
    executable = true;
  };

  # Toast icon for the change-notification, installed into hicolor and declared
  # as a seal so the panel paints it in the focus colour.
  home.file.".local/share/icons/hicolor/scalable/apps/repo-updates.svg".source =
    ../prog/app-icons/repo-updates.svg;
  my.appSeals = [ "repo-updates" ];

  home.packages = [
    (pkgs.writeShellScriptBin "nix-pull" ''
      # nix-pull            — show what origin/main has that this checkout does not
      # nix-pull apply      — pull it, rebuild through the host's wrapper, reload
      # nix-pull demo       — raise the toast, with its buttons, wired to nothing
      case "''${1:-check}" in
        apply|-a|--apply) exec ${pkgs.python3}/bin/python3 "$HOME/.config/scripts/repo-updates.py" --apply ;;
        check|-c|--check)  exec ${pkgs.python3}/bin/python3 "$HOME/.config/scripts/repo-updates.py" --check ;;
        demo|--demo)       exec ${pkgs.python3}/bin/python3 "$HOME/.config/scripts/repo-updates.py" --demo ;;
        *) echo "usage: nix-pull [check|apply|demo]" >&2; exit 2 ;;
      esac
    '')
  ];

  systemd.user.services.repo-updates = {
    Unit = {
      Description = "Offer ~/nix commits pushed from the other machine";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "simple";
      Restart = "on-failure";
      RestartSec = 10;
      # Pinned PATH for the survey, toast and rebuild wrappers; `%h` is not
      # expanded in Environment=.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.git pkgs.libnotify ]}:${config.home.homeDirectory}/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/run/wrappers/bin:/usr/bin:/bin"
      ];
      ExecStart = "${pkgs.python3}/bin/python3 %h/.config/scripts/repo-updates.py --daemon";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
