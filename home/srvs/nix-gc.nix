# Nix GC on `book`. `sys/base.nix` arms nix.gc on `top`, but that is a NixOS
# module and book gets home-manager only, so nothing had ever collected here:
# measured 2026-08-28, /nix/store had grown to 29G on a 62G root (92% full)
# against a 12.9 GiB live closure. Age alone is not enough — deleting
# generations older than 14d freed 0.8G, capping the count freed 13.5G — so
# this bounds both, then hard-links (book has no auto-optimise-store either;
# that setting is daemon-side and the daemon is Fedora's).
{ config, lib, pkgs, host, ... }:

lib.mkIf (host == "air") {
  systemd.user.services.nix-gc = {
    Unit.Description = "trim nix generations, collect garbage, optimise the store";
    Service = {
      Type = "oneshot";
      ExecStart = toString (pkgs.writeShellScript "nix-gc" ''
        set -u
        p="$HOME/.local/state/nix/profiles"
        for prof in "$p"/home-manager "$p"/profile; do
          [ -e "$prof" ] || continue
          ${pkgs.nix}/bin/nix-env --delete-generations +5 --profile "$prof" || true
        done
        ${pkgs.nix}/bin/nix-collect-garbage --delete-older-than 14d || true
        ${pkgs.nix}/bin/nix-store --optimise || true
      '');
    };
  };

  systemd.user.timers.nix-gc = {
    Unit.Description = "weekly nix GC";
    Timer = {
      OnCalendar = "weekly";
      Persistent = true;
      RandomizedDelaySec = "1h";
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
