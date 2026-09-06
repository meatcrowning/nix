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

      # Steam records installed games as app manifests rather than desktop
      # entries. Make launchers for those titles too, but not Steam's runtime
      # components, and do not duplicate a launcher Steam/the user already
      # provided with the same rungameid URL.
      for steamapps_dir in \
        "$HOME/.local/share/Steam/steamapps" \
        "$HOME/.steam/steam/steamapps" \
        "$HOME/.steam/root/steamapps"; do
        [ -d "$steamapps_dir" ] || continue
        while IFS= read -r -d $'\0' manifest; do
          appid=$(basename "$manifest" | sed -n 's/^appmanifest_\([0-9][0-9]*\)\.acf$/\1/p')
          name=$(sed -n 's/^[[:space:]]*"name"[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p' "$manifest" | head -n 1)
          [ -n "$appid" ] && [ -n "$name" ] || continue
          case "$name" in
            "Steam Linux Runtime"*|"Steamworks Common Redistributables") continue ;;
          esac
          already_linked=0
          for launcher in "$staging_dir"/*.desktop; do
            [ -e "$launcher" ] || continue
            if grep -Fqx "Exec=steam steam://rungameid/$appid" "$launcher"; then
              already_linked=1
              break
            fi
          done
          [ "$already_linked" = 0 ] || continue
          cat > "$staging_dir/steam-$appid.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Exec=steam steam://rungameid/$appid
Icon=steam_icon_$appid
Categories=Game;
Terminal=false
EOF
        done < <(find -L "$steamapps_dir" -maxdepth 1 -type f -name 'appmanifest_*.acf' -print0)
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
