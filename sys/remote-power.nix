# Rebooting and powering off `top` from away, without a password prompt.
#
# SSH is an inactive-seat session, so logind would otherwise ask for a dialog
# on a screen nobody is at. This module gives `lam` a fixed-verb wrapper
# instead: `status`, `reboot`, `reboot-force`, `reboot-sysrq`, and
# `poweroff --confirm`. The wrapper is the same NOPASSWD shape as
# `sys/nixos-rebuild.nix`, not `systemctl` itself.
#
# `poweroff` keeps a literal `--confirm` because off can strand the box when
# nothing on the LAN can wake it. `reboot-sysrq` is the emergency path when
# userspace is gone; `kernel.sysrq` is raised to 176 so sync + remount-ro +
# reboot all land.
#
# NixOS-only, so `book` does not get it.
{ pkgs, ... }:

let
  remotePower = pkgs.writeShellScriptBin "remote-power" ''
    set -u
    PATH=${pkgs.lib.makeBinPath [ pkgs.coreutils pkgs.systemd pkgs.procps ]}:$PATH

    usage() {
      cat >&2 <<'EOF'
    remote-power <verb>

      status                  what this box is doing (touches nothing)
      reboot                  clean reboot (systemctl reboot)
      reboot-force            skip the unit shutdown (systemctl reboot -ff)
      reboot-sysrq            kernel-level: sync, remount read-only, reset
      poweroff --confirm      power off. STRANDS the box unless something on its
                              LAN can send it a wake-on-LAN packet.
    EOF
      exit 2
    }

    [ "$#" -ge 1 ] || usage

    case "$1" in
      status)
        [ "$#" -eq 1 ] || usage
        echo "host:      $(hostname)"
        echo "uptime:    $(uptime | sed 's/^ *//')"
        echo "booted:    $(readlink -f /run/booted-system)"
        echo "current:   $(readlink -f /run/current-system)"
        echo "watchdog:  $(cat /sys/class/watchdog/watchdog0/state 2>/dev/null || echo none)" \
             "timeout=$(cat /sys/class/watchdog/watchdog0/timeout 2>/dev/null || echo -)s" \
             "timeleft=$(cat /sys/class/watchdog/watchdog0/timeleft 2>/dev/null || echo -)s"
        echo "runtimewd: $(systemctl show -p RuntimeWatchdogUSec --value)"
        echo "memfree:   $(free -h | awk '/^Mem:/{print $7" available of "$2}')"
        echo "sshd:      $(systemctl is-active sshd)"
        echo "unclean boots recorded:"
        tail -5 /var/log/watchdog-resets.log 2>/dev/null | sed 's/^/  /' || echo "  (none)"
        ;;

      reboot)
        [ "$#" -eq 1 ] || usage
        echo "remote-power: clean reboot" >&2
        exec systemctl reboot
        ;;

      reboot-force)
        [ "$#" -eq 1 ] || usage
        echo "remote-power: forced reboot, skipping the unit shutdown" >&2
        exec systemctl reboot -ff
        ;;

      reboot-sysrq)
        [ "$#" -eq 1 ] || usage
        echo "remote-power: sysrq sync + remount-ro + reset" >&2
        sync
        echo s > /proc/sysrq-trigger; sleep 3
        echo u > /proc/sysrq-trigger; sleep 3
        echo b > /proc/sysrq-trigger
        ;;

      poweroff)
        # Deliberately awkward: off can strand the box when nothing on the LAN
        # can wake it.
        if [ "$#" -ne 2 ] || [ "$2" != "--confirm" ]; then
          echo "remote-power: poweroff needs --confirm (nothing may be able to wake this box)" >&2
          exit 2
        fi
        echo "remote-power: powering off" >&2
        exec systemctl poweroff
        ;;

      *) usage ;;
    esac
  '';
in
{
  # 16 (sync) is the stock value here; `reboot-sysrq` also needs remount-ro
  # and reboot, or the write to /proc/sysrq-trigger succeeds and nothing
  # happens.
  boot.kernel.sysctl."kernel.sysrq" = 176; # 16 sync | 32 remount-ro | 128 reboot

  # Both the /run/current-system symlink and the resolved store path, for the
  # same reason sys/nixos-rebuild.nix lists both.
  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = [
      { command = "/run/current-system/sw/bin/remote-power"; options = [ "NOPASSWD" ]; }
      { command = "${remotePower}/bin/remote-power"; options = [ "NOPASSWD" ]; }
    ];
  }];

  environment.systemPackages = [ remotePower ];
}
