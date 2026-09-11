{ config, pkgs, lib, ... }:

# labwc — a wlroots stacking compositor, installed alongside Hyprland and
# Plasma as a third session to try. The greeter entry is registered on the
# NixOS side (sys/dsk/labwc.nix); this module supplies the two GUI config tools
# and seeds ~/.config/labwc.
#
# HOST EXCEPTION: top only. book is Fedora Asahi with no binary cache for
# aarch64, so the compositor and the Qt tweaks app would both be long source
# builds for a session book has no greeter entry for. Drop the guard (and add
# the session another way) if labwc is ever wanted there.
let
  onTop = pkgs.stdenv.hostPlatform.isx86_64;
in
{
  home.packages = lib.optionals onTop [
    pkgs.labwc                 # the compositor, for `labwc --help` / nested runs
    pkgs.labwc-tweaks          # Qt config GUI; rewrites ~/.config/labwc/rc.xml
    pkgs.labwc-menu-generator  # writes ~/.config/labwc/menu.xml from .desktop files
  ];

  # SEED ONCE, never reconcile. labwc-tweaks serialises the whole of rc.xml on
  # every save, so the runtime copies are authored by that tool and by hand,
  # not by this repo — the hyprland.lua / Theme.qml reconcile path
  # (tools/seed-reconcile.sh) would discard the work on the next switch. These
  # files are therefore installed only when missing, which is also why they are
  # not in tools/seed-drift.sh's PAIRS: drift here is the intended state, not
  # the fault.
  #
  # menu.xml IS seeded, and has to be: labwc 0.20 has no built-in fallback
  # menu, so without the file a right-click on the desktop opens nothing at all
  # and Reconfigure/Exit are unreachable. The seed reaches the application list
  # through a pipe menu that runs labwc-menu-generator on open, so the list
  # stays current without any file being regenerated.
  home.activation.seedLabwcConfig = lib.mkIf onTop
    (lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      seed_labwc() {
        local src="$1" dst="$HOME/.config/labwc/$2" mode="$3"
        [ -e "$dst" ] && return 0
        run install -D -m"$mode" "$src" "$dst"
      }
      seed_labwc ${./labwc-files/rc.xml}       rc.xml      644
      seed_labwc ${./labwc-files/menu.xml}     menu.xml    644
      seed_labwc ${./labwc-files/environment}  environment 644
      seed_labwc ${./labwc-files/autostart}    autostart   755
    '');
}
