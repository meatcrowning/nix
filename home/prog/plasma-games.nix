{ config, pkgs, lib, ... }:

let
  gamesDirectory = "${config.xdg.dataHome}/plasma-games";
  refreshGames = pkgs.writeShellApplication {
    name = "plasma-games-refresh";
    runtimeInputs = [ pkgs.coreutils pkgs.findutils pkgs.gnugrep ];
    text = ''
      set -eu

      games_dir=${lib.escapeShellArg gamesDirectory}
      staging_dir="$games_dir.new.$$"
      trap 'rm -rf "$staging_dir"' EXIT
      mkdir -p "$staging_dir"

      # The ordered sources match XDG desktop-file lookup precedence. A game
      # installed on this host in a user profile shadows a same-named system
      # launcher, and only its launcher is placed in the Folder View.
      for applications_dir in \
        "$HOME/.local/share/applications" \
        "$HOME/.nix-profile/share/applications" \
        "/etc/profiles/per-user/$USER/share/applications" \
        "/run/current-system/sw/share/applications"; do
        [ -d "$applications_dir" ] || continue
        while IFS= read -r -d $'\0' desktop_file; do
          desktop_name=$(basename "$desktop_file")
          [ -e "$staging_dir/$desktop_name" ] && continue
          grep -qx 'Type=Application' "$desktop_file" || continue
          grep -Eq '^Categories=([^;]*;)*Game(;|$)' "$desktop_file" || continue
          grep -Eq '^(Hidden|NoDisplay)=true$' "$desktop_file" && continue
          ln -s "$desktop_file" "$staging_dir/$desktop_name"
        done < <(find -L "$applications_dir" -type f -name '*.desktop' -print0)
      done

      rm -rf "$games_dir"
      mv "$staging_dir" "$games_dir"
      trap - EXIT
    '';
  };
in
{
  # Folder View watches this directory. It contains only links to launchers
  # whose desktop entry declares the standard Game category, so top and air
  # naturally show their own installed games rather than a shared inventory.
  home.activation.refreshPlasmaGames = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    $DRY_RUN_CMD ${refreshGames}/bin/plasma-games-refresh
  '';

  systemd.user.services.plasma-games-refresh = {
    Unit.Description = "refresh the Plasma games folder";
    Service = {
      Type = "oneshot";
      ExecStart = "${refreshGames}/bin/plasma-games-refresh";
    };
  };

  # Desktop entries can arrive outside a rebuild (for example from a local
  # install). Watch the normal XDG/profile locations and retain a timer as a
  # reliable fallback for profile symlink changes that do not emit an event.
  systemd.user.paths.plasma-games-refresh = {
    Unit.Description = "notice installed or removed game launchers";
    Path.PathChanged = [
      "%h/.local/share/applications"
      "%h/.nix-profile/share/applications"
      "/etc/profiles/per-user/%u/share/applications"
      "/run/current-system/sw/share/applications"
    ];
    Install.WantedBy = [ "default.target" ];
  };
  systemd.user.timers.plasma-games-refresh = {
    Unit.Description = "periodically refresh the Plasma games folder";
    Timer = {
      OnBootSec = "1min";
      OnUnitActiveSec = "15min";
      Unit = "plasma-games-refresh.service";
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
