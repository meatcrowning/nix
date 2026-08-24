{ pkgs, ... }:

# Hold `[ColorEffects:Inactive] Enable=false` in `~/.config/kdeglobals`.
#
# The effect dulls an unfocused window's whole surface (his scheme:
# ColorAmount -0.9), but only half that surface is KWin's: the titlebar dims
# with the deco while the menubar and client stay bright, because the apps
# pin one palette group (apps/pylib/kdeshell.py) and nothing app-side can see
# the deco's opinion. A Spectacle window grab takes KWin's active window away
# without taking the client's wl_keyboard focus, so every capture of a focused
# window came out with a dull titlebar over a lit menubar — reported three
# times.
#
# `home/plasma.nix` already declares the key, but plasma-manager writes it once
# at login (overrideConfig = false), and applying a colour scheme or a global
# theme copies that scheme's own ColorEffects block straight back over it. So
# the declaration alone does not hold: this re-asserts it whenever kdeglobals
# changes, which is the only moment it can be lost.
#
# The write cannot loop — it only fires when the value is not already false,
# and the re-trigger from its own write finds it false and exits.

let
  script = pkgs.writeShellScript "kde-inactive-effect" ''
    kg="$HOME/.config/kdeglobals"
    [ -f "$kg" ] || exit 0
    cur=$(${pkgs.kdePackages.kconfig}/bin/kreadconfig6 --file "$kg" \
            --group "ColorEffects:Inactive" --key Enable)
    [ "$cur" = "false" ] && exit 0
    ${pkgs.kdePackages.kconfig}/bin/kwriteconfig6 --file "$kg" \
      --group "ColorEffects:Inactive" --key Enable false
    ${pkgs.dbus}/bin/dbus-send --session --dest=org.kde.KWin \
      --type=method_call /KWin org.kde.KWin.reconfigure 2>/dev/null || true
    echo "kde-inactive-effect: was '$cur', put back to false"
  '';
in
{
  systemd.user.services.kde-inactive-effect = {
    Unit.Description = "Keep the KDE inactive colour effect off";
    Service = {
      Type = "oneshot";
      ExecStart = "${script}";
    };
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.paths.kde-inactive-effect = {
    Unit.Description = "Watch kdeglobals for the inactive colour effect";
    Path.PathChanged = "%h/.config/kdeglobals";
    Install.WantedBy = [ "default.target" ];
  };
}
