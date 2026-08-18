{ pkgs, lib, host, ... }:

# A real temp/fan history, sampled once a minute, because none existed at all
# (docs/top-thermal-history.md — checked journald, timers, cron, the panel's
# own live poll, everything under ~/.cache and ~/.local: nothing persists a
# sample). On `top` this is also the only thing worth having: the nct6683
# driver marks every pwm node read-only for this board's customer ID, so
# there is no in-OS fan control to fall back on, only the UEFI curve — a
# sampled log is the one lever left for judging sustained-load behavior
# after the fact.
#
# `top` ONLY. The sampler still degrades per-field rather than per-host, but on
# book there is nothing left to degrade TO: the M1 Air is fanless (no fan hwmon,
# no pwm — docs/HARDWARE.md) and has no NVIDIA GPU, so every sample there was
# `"gpu_temp_c":null,"fans":[]` around a single battery-hotspot number. A
# minutely timer writing that is cost with no reading in it.
#
# Writes ~/.local/state/thermal-history/<hostname>.jsonl (hostname, not the
# flake attribute — top/book, matching the board's own per-host convention).
# Self-bounding: the script trims the file back down whenever it crosses 8
# MiB, so it cannot grow unbounded on a root fs that already runs >80% full.
lib.mkIf (host == "top") {
  xdg.configFile."scripts/thermal-history-sample.sh" = {
    source = ./thermal-history-files/sample.sh;
    executable = true;
  };

  systemd.user.services.thermal-history = {
    Unit.Description = "Sample CPU/GPU temp + fan RPMs into a JSONL history";
    Service = {
      Type = "oneshot";
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.coreutils
          pkgs.gawk
          pkgs.gnugrep
        ]}:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = "/bin/sh %h/.config/scripts/thermal-history-sample.sh";
      TimeoutStartSec = "30s";
    };
  };

  systemd.user.timers.thermal-history = {
    Unit.Description = "Sample temps/fans every minute";
    Timer = {
      OnStartupSec = "1min";
      OnUnitActiveSec = "1min";
      Persistent = false;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
