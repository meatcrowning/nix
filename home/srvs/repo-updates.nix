{ pkgs, lib, config, ... }:

# "The other machine pushed" — as a toast with buttons on it.
#
# Everything else that crosses the two machines syncs itself: docs/ every 5
# minutes (nix-docs.nix), the whole of ~/.claude on the same cadence
# (claude-state.nix). ~/nix does not, and cannot sensibly: pulling the flake is
# only half of landing it, the other half is a switch that swaps the machine you
# are sitting at. So the pull stays a decision — and this makes the decision
# reachable instead of remembered.
#
# The daemon (repo-updates-files/repo-updates.py, and the reasoning is in its
# docstring) checks origin/main at session start, on resume from suspend and on
# a slow poll, then offers a persistent toast carrying what the change will
# COST: a compositor pin bump means a from-source Hyprland build on book and no
# live plugin hot-swap either way, while an apps/-only change means no rebuild
# at all. Click "Pull & apply" and it pulls, rebuilds through the host's own
# wrapper (which owns preflight and the shared rebuild lock) and reloads what
# can be reloaded; click "Dismiss" and it stays quiet until something NEWER
# lands.
#
# BOTH MACHINES, one file: the host branch is inside the script (`sudo
# rebuild-top` vs `rebuild-air`), because everything else about it — the fetch,
# the classifier, the toast, the resume detection — is identical on top and
# book.
#
# WHY IT IS A DAEMON and not a timer + a path unit like its board-* siblings:
# it has to be holding a `notify-send -w` when he clicks the button. That call
# blocks until the toast closes and prints which action was invoked, and there
# is nothing else in the freedesktop protocol that tells a one-shot which button
# a person pressed minutes later.
#
# `nix-pull` is the same code with no toast: the by-hand entry point, and what
# the toast falls back to naming when notification actions are switched off in
# the panel.

{
  xdg.configFile."scripts/repo-updates.py" = {
    source = ./repo-updates-files/repo-updates.py;
    executable = true;
  };

  # The toast's own seal — Gaap, who carries a change from one machine to the
  # other (home/prog/app-icons/repo-updates.svg). The daemon sends it with
  # `-i repo-updates`; installed into hicolor so the name resolves, and declared
  # a SEAL so the panel paints its currentColor strokes in the focus colour
  # instead of the file's baked fallback (home/prog/app-icons/seals.nix).
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
      # Pinned PATH, same shape and same reason as board-notify.service: the
      # ambient systemd-user PATH reaches none of this. `git` and `nix` do the
      # survey, `notify-send` raises the toast, and the profile tail is where
      # the rebuild wrappers live — `rebuild-air` on book (a writeShellScriptBin
      # in the home profile), `sudo`/`rebuild-top` on top. The nix daemon
      # profile is named explicitly for `nix build --dry-run` — that is where
      # book's `nix` lives, outside every other entry here. NOT `%h`: systemd
      # expands specifiers in ExecStart but not in Environment=.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.git pkgs.libnotify ]}:${config.home.homeDirectory}/.nix-profile/bin:/nix/var/nix/profiles/default/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/run/wrappers/bin:/usr/bin:/bin"
      ];
      ExecStart = "${pkgs.python3}/bin/python3 %h/.config/scripts/repo-updates.py --daemon";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
