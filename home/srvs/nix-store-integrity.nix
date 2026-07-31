{ pkgs, lib, ... }:

# Weekly read-only content check of /nix/store, because bit rot here is silent.
# The incident and the sizing of this unit are in
# docs/agents/nix-store-bitrot-extent.md; the script's own header explains why
# it re-hashes every .drv every run but only a rotating eighth of everything
# else.
#
# Deliberately a USER unit with no root: `nix-store --verify-path` is read-only
# and takes no db lock, so this can never collide with a rebuild, and it needs
# nothing from `sys/` — which also means it applies on book unchanged.
#
# It surfaces nothing by itself. `tools/preflight.sh` reads
# ~/.local/state/nix-store-integrity/corrupt.txt and warns before a rebuild,
# which is when a rotted store path actually costs something.

{
  xdg.configFile."scripts/nix-store-integrity.sh" = {
    source = ./nix-store-integrity-files/nix-store-integrity.sh;
    executable = true;
  };

  systemd.user.services.nix-store-integrity = {
    Unit.Description = "Re-hash part of /nix/store to catch silent corruption";
    Service = {
      Type = "oneshot";
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.coreutils
          pkgs.findutils
          pkgs.gnugrep
          pkgs.gnused
          pkgs.gawk
          pkgs.util-linux # ionice
          pkgs.nix
        ]}"
      ];
      ExecStart = "${pkgs.bash}/bin/bash %h/.config/scripts/nix-store-integrity.sh";
      # A slice is minutes, not hours; a run that overruns this badly is a sign
      # the disk is in trouble and should be killed rather than left grinding.
      TimeoutStartSec = "2h";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
  };

  systemd.user.timers.nix-store-integrity = {
    Unit.Description = "Weekly /nix/store integrity slice";
    Timer = {
      OnCalendar = "weekly";
      # An hour of jitter so it never lands on top of a login.
      RandomizedDelaySec = "1h";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
