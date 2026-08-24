{ pkgs, ... }:

# Hold `[ColorEffects:Inactive] Enable=false` in `~/.config/kdeglobals`.
#
# The colour-scheme inactive effect is the WRONG half of the desktop doing the
# dimming. It gives an unfocused window a second set of colours (his scheme:
# ColorEffect 1, ColorAmount -0.9), and the two halves of one window decide
# which set to use from different places: KWin's deco from the window it
# considers active, the client from whether Qt still holds keyboard focus.
# A Spectacle grab separates them — Qt deactivates while KWin's deco does not.
#
# Measured on `top` 2026-08-24, off a capture of a FOCUSED chatter: the client
# rendered (44,62,97) at the top of the menubar and the deco (54,63,84) at the
# bottom of the titlebar, which are Oxygen's window background rendered in the
# INACTIVE and the ACTIVE colour group respectively — a hard seam where the one
# gradient the two halves share is supposed to run through. Reported three
# times.
#
# `home/plasma.nix` turns KWin's **Dim Inactive** effect on in its place: one
# compositor scrim over deco and client together, which cannot disagree with
# itself. Same shape as the Hyprland side, `decoration:dim_inactive` —
# docs/DESIGN.md §3.1.1, "an unfocused window dims WHOLE, one native scrim".
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
