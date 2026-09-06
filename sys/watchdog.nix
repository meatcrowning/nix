# The hardware watchdog is the backstop behind `sys/oomd.nix`: PID1 pets
# `/dev/watchdog0`, and if the kernel can no longer schedule PID1 the chip
# resets the box without software being involved.
#
# It is armed only on `top` because this is the machine that must recover from a
# livelock remotely. `RuntimeWatchdogSec=5min` is long enough for heavy memory
# pressure to settle, and `watchdog-record` logs unclean boots while disarming
# the watchdog after three in an hour so a loop does not power-cycle forever.
# `book` does not get this policy.
#
#   cat /var/log/watchdog-resets.log              # every unclean boot, newest last
#   wdctl /dev/watchdog0                          # is the timer actually armed?
#   cat /sys/class/watchdog/watchdog0/bootstatus  # 32 (WDIOF_CARDRESET) = the chip did it
{ pkgs, ... }:

let
  record = pkgs.writeShellScript "watchdog-record" ''
    set -u
    PATH=${pkgs.lib.makeBinPath [ pkgs.coreutils pkgs.gawk pkgs.gnugrep pkgs.systemd ]}

    LOG=/var/log/watchdog-resets.log
    STATE=/var/lib/watchdog-record
    WD=/sys/class/watchdog/watchdog0
    mkdir -p "$STATE"

    now_iso=$(date -Is)
    now_epoch=$(date +%s)

    # Once per BOOT, not once per start. The unit restarts on every rebuild, so
    # a second entry for the same dead boot would be both a lie and a false
    # vote toward the loop guard.
    this_boot=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -d '-')
    if [ -n "$this_boot" ] && [ "$this_boot" = "$(cat "$STATE/last-boot-id" 2>/dev/null)" ]; then
      exit 0
    fi

    # WDIOF_CARDRESET (0x20) is the chip saying it fired. Not every driver
    # reports it, so an unclean previous boot is the weaker fallback signal.
    bootstatus=$(cat "$WD/bootstatus" 2>/dev/null || echo 0)
    case "$bootstatus" in (*[!0-9]*|"") bootstatus=0 ;; esac

    # A boot that ended on purpose says so in its last few lines. One that was
    # reset, panicked or lost power just stops.
    prev_id=$(journalctl --list-boots -o json 2>/dev/null \
      | grep -o '"boot_id" *: *"[0-9a-f]*"' | tail -2 | head -1 \
      | grep -o '[0-9a-f]\{32\}' || true)
    prev_tail=$(journalctl -b -1 -n 60 --no-pager -o cat 2>/dev/null || true)

    if [ -z "$prev_tail" ]; then
      verdict=no-previous-boot
    elif printf '%s\n' "$prev_tail" | grep -qE 'Reached target (Power-Off|Reboot|Halt|Shutdown)|Powering off|Rebooting|systemd-shutdown'; then
      verdict=clean
    else
      verdict=unclean
    fi

    if [ "$(( bootstatus & 32 ))" -ne 0 ]; then
      cause="watchdog reset (bootstatus=$bootstatus)"
    elif [ "$verdict" = unclean ]; then
      cause="unclean shutdown - watchdog, panic or power loss"
    else
      exit 0   # nothing happened; say nothing
    fi

    [ -n "$this_boot" ] && echo "$this_boot" > "$STATE/last-boot-id"
    echo "$now_epoch" >> "$STATE/events"
    # Keep only the last hour. Never clobber the tally on a failure: an empty
    # events file is a disarmed loop guard, which is the one thing this must
    # not fail into.
    cutoff=$(( now_epoch - 3600 ))
    if awk -v c="$cutoff" '$1 >= c' "$STATE/events" > "$STATE/events.new"; then
      mv "$STATE/events.new" "$STATE/events"
    else
      rm -f "$STATE/events.new"
    fi
    recent=$(wc -l < "$STATE/events" 2>/dev/null || echo 1)
    [ -n "$recent" ] || recent=1

    printf '%s  %s  (previous boot %s, %s in the last hour)\n' \
      "$now_iso" "$cause" "''${prev_id:-unknown}" "$recent" >> "$LOG"

    if [ "$recent" -ge 3 ]; then
      mkdir -p /run/systemd/system.conf.d
      printf '[Manager]\nRuntimeWatchdogSec=0\n' \
        > /run/systemd/system.conf.d/90-watchdog-loopguard.conf
      systemctl daemon-reexec || true
      printf '%s  LOOP GUARD: watchdog disarmed for this boot after %s unclean boots in an hour\n' \
        "$now_iso" "$recent" >> "$LOG"
      echo "watchdog disarmed: $recent unclean boots inside an hour" >&2
    fi
  '';
in
{
  # PID1 pets the timer every runtimeTime/2; the chip resets the box if it goes
  # five minutes unpetted. `rebootTime` is the separate ceiling on a requested
  # reboot hanging (`sys/remote-power.nix` carries the escape hatches).
  systemd.watchdog = {
    runtimeTime = "5min";
    rebootTime = "10min";
  };

  systemd.services.watchdog-record = {
    description = "Record unclean boots and guard against a watchdog reboot loop";
    after = [ "systemd-journald.service" ];
    requires = [ "systemd-journald.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = record;
    };
  };
}
