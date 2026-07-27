{ pkgs, lib, host, ... }:

# filer as the desktop's FILE PICKER — the `org.freedesktop.impl.portal.FileChooser`
# D-Bus backend (source: ~/nix/apps/filer/portal.py + pick.py).
#
# This is a different mechanism from filer being the default *directory handler*
# (that is a MIME association, and lives in home/prog/filer.nix +
# home/prog/mime-defaults.nix). A file picker is what appears when Firefox says
# "Upload File" — the app calls xdg-desktop-portal, which calls whichever
# backend is configured for the FileChooser interface.
#
# SHIPS DORMANT, AND STAYS DORMANT UNTIL THE USER FLIPS IT.
#
#   filer-portal-switch status | on | off
#
# Installing the `.portal` file below changes NOTHING on its own — verified
# empirically against xdg-desktop-portal 1.22.1: xdp only ever consults backends
# NAMED in a portals.conf, and reaches for an unnamed one solely as a
# last-resort fallback when no configured backend exists at all. Here
# `/usr/share/xdg-desktop-portal/hyprland-portals.conf` (book) and
# `/etc/xdg-desktop-portal/hyprland-portals.conf` (top, from
# sys/dsk/hyprland.nix) both resolve fine already, so a `filer.portal` sitting
# on disk is inert. `filer-portal-switch on` is the whole activation, and it
# writes exactly one user-level file that `off` deletes again.
#
# Why a script rather than a nix option: turning this OFF must not require a
# rebuild. A file dialog that fails to appear is the kind of breakage you want
# to undo in one second, from any shell, before you know why.
let
  # portal.py needs PyGObject (Gio/GLib) — the D-Bus + main-loop layer — and
  # nothing else. It deliberately does NOT import Qt: the backend is a tiny
  # long-lived service, and the QML lives in the `filer --pick` subprocess it
  # spawns. On air (book) that is Fedora's python3, which already has gi, for
  # the same Mesa reason home/prog/filer.nix documents.
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pygobject3 ]);
  python = if host == "air" then "/usr/bin/python3" else "${pyEnv}/bin/python3";

  # Which backend answers SaveFile/SaveFiles (and OpenFile, if the picker can't
  # start). Portal backend selection is per-INTERFACE, not per-method, so
  # claiming FileChooser means claiming all three methods — portal.py forwards
  # the two it has no UI for to whoever is answering them today. That is `kde`
  # on top (sys/dsk/hyprland.nix routes FileChooser there) and `gtk` on book,
  # where the configured `hyprland` backend is not installed and xdp falls
  # through to gtk.
  delegate = if host == "air" then "gtk" else "kde";

  filer-portal = pkgs.writeShellScriptBin "filer-portal" ''
    # D-Bus activation gives this a minimal PATH that need not include the nix
    # profile, and portal.py resolves `filer` from PATH before falling back.
    export PATH="$HOME/.nix-profile/bin:/run/current-system/sw/bin:$PATH"
    export FILER_PORTAL_DELEGATE="''${FILER_PORTAL_DELEGATE:-${delegate}}"
    exec ${python} /home/lam/nix/apps/filer/portal.py "$@"
  '';

  # The routing the switch writes. It must restate the whole desktop's
  # preferences, not just FileChooser: a portals.conf found in a
  # higher-precedence directory SHADOWS the lower one entirely rather than
  # merging with it, so anything omitted here silently reverts to xdp's
  # defaults. These lines mirror what each host resolves to today, with
  # FileChooser pointed at filer and the previous answer kept behind it.
  preferred = if host == "air" then ''
    [preferred]
    default=hyprland;gtk
    org.freedesktop.impl.portal.FileChooser=filer;gtk
  '' else ''
    [preferred]
    default=hyprland;gtk
    org.freedesktop.impl.portal.FileChooser=filer;kde
    org.freedesktop.impl.portal.Settings=kde
  '';

  # …materialised into the store, so the switch script is a `cp` and there is no
  # heredoc whose indentation has to survive both nix's string stripping and the
  # shell's.
  preferredFile = pkgs.writeText "filer-hyprland-portals.conf" preferred;

  filer-portal-switch = pkgs.writeShellScriptBin "filer-portal-switch" ''
    set -euo pipefail
    conf="$HOME/.config/xdg-desktop-portal/hyprland-portals.conf"

    reload() {
      # 1. D-Bus caches its list of activatable services. A .service file that
      #    appeared since login is NOT activatable until this reload — the
      #    failure mode is "The name is not activatable", i.e. the very hang
      #    this whole design exists to avoid, on the first dialog after a fresh
      #    home-manager switch. Cheap and idempotent, so it runs on `off` too.
      busctl --user call org.freedesktop.DBus /org/freedesktop/DBus \
             org.freedesktop.DBus ReloadConfig >/dev/null 2>&1 || true
      # 2. Drop any running backend so the next request activates the current
      #    build rather than a stale process.
      pkill -f 'apps/filer/portal.py' 2>/dev/null || true
      # 3. xdp reads its configuration once, at startup. Restarting it is
      #    enough — it is D-Bus-activated, so the next dialog brings it back.
      systemctl --user restart xdg-desktop-portal.service 2>/dev/null || true
    }

    case "''${1-status}" in
      on)
        mkdir -p "$(dirname "$conf")"
        install -m 0644 ${preferredFile} "$conf"
        echo "filer is now the FileChooser backend ($conf)"
        reload
        echo "revert at any time with: filer-portal-switch off"
        ;;
      off)
        rm -f "$conf"
        rmdir "$(dirname "$conf")" 2>/dev/null || true
        echo "reverted to the system default FileChooser backend"
        reload
        ;;
      status)
        if [ -f "$conf" ]; then
          echo "ON  — $conf:"
          sed 's/^/    /' "$conf"
        else
          echo "OFF — no $conf; the system default is in effect"
        fi
        echo
        echo "backend service: ${filer-portal}/bin/filer-portal"
        echo "to see what xdp actually picks:"
        echo "  systemctl --user stop xdg-desktop-portal.service"
        echo "  G_MESSAGES_DEBUG=all /usr/libexec/xdg-desktop-portal -v 2>&1 | grep FileChooser"
        ;;
      *)
        echo "usage: filer-portal-switch [status|on|off]" >&2
        exit 2
        ;;
    esac
  '';
in
{
  home.packages = [ filer-portal filer-portal-switch ];

  # The backend declaration. Inert until a portals.conf names `filer` — see the
  # header. xdp searches $XDG_DATA_HOME/xdg-desktop-portal/portals regardless of
  # what XDG_DATA_DIRS the D-Bus activation environment carries (confirmed from
  # its own "load portals from …" trace), which matters on book: the activation
  # environment there has no nix profile on XDG_DATA_DIRS at all.
  #
  # `home.file` rather than `xdg.dataFile` because xdg.enable is off in this
  # configuration — same reason home/prog/filer.nix writes its .desktop by hand.
  home.file.".local/share/xdg-desktop-portal/portals/filer.portal".text = ''
    [portal]
    DBusName=org.freedesktop.impl.portal.desktop.filer
    Interfaces=org.freedesktop.impl.portal.FileChooser;
    UseIn=Hyprland
  '';

  # D-Bus activation, so xdp starts the backend on the first dialog instead of
  # it needing to be running already.
  home.file.".local/share/dbus-1/services/org.freedesktop.impl.portal.desktop.filer.service".text = ''
    [D-BUS Service]
    Name=org.freedesktop.impl.portal.desktop.filer
    Exec=${filer-portal}/bin/filer-portal
  '';
}
