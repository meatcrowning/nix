# The hardware watchdog, armed — so a livelocked `top` reboots itself.
#
# `sys/oomd.nix` is the first line against the memory livelock and it is a
# userspace daemon: it needs to be scheduled to act, which is exactly what a
# box in that state stops doing. This is the line behind it. PID1 pets
# `/dev/watchdog0` (the board's SP5100 TCO timer) every RuntimeWatchdogSec/2;
# a kernel that can no longer schedule PID1 stops petting, and the chip resets
# the machine with no software involved at all.
#
# It exists because there is NO WAY TO UNWEDGE `top` REMOTELY. Wake-on-LAN
# (`sys/net/wol.nix`) only covers a machine that is genuinely off — a livelock
# leaves the NIC up and the kernel unable to act on anything it receives — and
# the fallbacks for that (a second machine on the LAN, a switched plug) were
# not available on 2026-08-26. This one needs nothing but the board.
#
# TWO MINUTES, not the 60s default the driver ships. The trigger here is heavy
# memory pressure, which stalls a desktop hard for tens of seconds and then
# recovers; a short timer would turn a survivable stall into a reset. Two
# minutes is past anything this box has come back from.
#
# THE LOOP GUARD is the point of `watchdog-record`. An unattended reset that
# lands straight back in the state that caused it is a boot loop, and a box
# power-cycling itself every four minutes while nobody is home is worse than a
# box that is simply down. So every unclean boot is recorded, and the THIRD
# inside an hour DISARMS the watchdog for that boot (a `/run` drop-in plus a
# re-exec, so nothing persists past the next real boot). The machine then stays
# down, or stays wedged, and waits to be looked at.
#
# The record it leaves is `/var/log/watchdog-resets.log` — one line per unclean
# boot, naming the cause and the boot id of the boot that died, so
# `journalctl -b <id>` reaches the evidence afterwards. Nothing can be written
# AT the reset (that is what a hardware reset means), so this reconstructs it
# on the way back up.
#
# NixOS-only, so `book` does not get it. It is a laptop with a battery and a
# lid, it is not the machine anyone needs to reach from away, and its watchdog
# policy is Fedora's.
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

    # Once per BOOT, not once per start. The unit restarts on every
    # nixos-rebuild, and a second entry for the same dead boot is both a lie in
    # the log and a false vote toward the loop guard — three rebuilds in an
    # hour would have disarmed the watchdog.
    this_boot=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -d '-')
    if [ -n "$this_boot" ] && [ "$this_boot" = "$(cat "$STATE/last-boot-id" 2>/dev/null)" ]; then
      exit 0
    fi

    # WDIOF_CARDRESET (0x20) is the chip saying it fired. Not every driver
    # reports it, so an unclean previous boot is the second, weaker signal.
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
    # Keep only the last hour. Never clobber the tally on a failure here: an
    # empty events file is a DISARMED loop guard, which is the one thing this
    # must not fail into (it did, for want of awk on the PATH).
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
  # PID1 pets the timer every 60s; the chip resets the box if it goes 2 minutes
  # unpetted. rebootTime is the separate ceiling on a REQUESTED reboot hanging.
  systemd.watchdog = {
    runtimeTime = "2min";
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
