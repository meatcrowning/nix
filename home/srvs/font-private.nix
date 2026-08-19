{ pkgs, lib, ... }:

# Private mechanism for fonts that cannot live in the PUBLIC ~/nix checkout.
#
# Tahoma is proprietary Microsoft TrueType and is not in any free pack, so the
# binary must not be committed to meatcrowning/nix. The user chose (board
# 2026-08-18) to source it via a claude-state-style PRIVATE repo instead of
# leaving it top-only. This module deploys a fetch-and-install script and
# drives it from a systemd user unit + timer, plus a home.activation hook so
# the very switch that adds this module installs the font on this machine.
#
# The repo is meatcrowning/nix-fonts (PRIVATE). Only this mechanism ever writes
# it, so the sync is one-way read: clone once, fast-forward to origin/main, copy
# the font out. Authentication is the gh credential helper (`!gh auth
# git-credential`), exactly like claude-state-sync and nix-docs-sync.
#
# Both machines get this: `home/` is shared verbatim between `top` and `air`,
# and Fedora Asahi runs systemd the same as NixOS.

let
  # git for the clone/fetch, gh for the credential helper, coreutils for the
  # copy, fontconfig for fc-cache. The ambient systemd-user PATH cannot be
  # relied on for any of them.
  installPath = lib.makeBinPath [
    pkgs.git
    pkgs.gh
    pkgs.coreutils
    pkgs.fontconfig
  ];
in
{
  xdg.configFile."scripts/font-private-install.sh" = {
    source = ./font-private-files/font-private-install.sh;
    executable = true;
  };

  # Install on the switch that lands this module — so top gets the font the
  # moment this is activated, and book on its next `home-manager switch`.
  home.activation.installPrivateFonts = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [ -x "$HOME/.config/scripts/font-private-install.sh" ]; then
      PATH=${installPath} "$HOME/.config/scripts/font-private-install.sh" \
        || true
    fi
  '';

  systemd.user.services.font-private-sync = {
    Unit.Description = "Fetch proprietary fonts from the private nix-fonts repo";
    Service = {
      Type = "oneshot";
      Environment = [ "PATH=${installPath}" ];
      ExecStart = "%h/.config/scripts/font-private-install.sh";
    };
  };

  systemd.user.timers.font-private-sync = {
    Unit.Description = "Periodically refresh proprietary fonts from nix-fonts";
    Timer = {
      OnBootSec = "3min";
      # Must accompany OnBootSec in a USER manager (see nix-docs.nix for the
      # 14-hour outage that proved it): OnBootSec counts from system boot, but
      # the user manager starts at login, so a late login leaves the only
      # elapse point in the past and the timer never fires.
      OnStartupSec = "3min";
      OnUnitActiveSec = "24h";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
