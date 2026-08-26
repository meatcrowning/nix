# Rebooting and powering off `top` FROM AWAY, without a password prompt.
#
# It could not be done at all until 2026-08-26, and nothing said so. An ssh
# session is a REMOTE, inactive-seat session, so logind's polkit policy answers
# `auth_admin_keep` for `org.freedesktop.login1.reboot` — a password dialog on a
# screen nobody is sitting at — and `sudo` covers only `rebuild-top`
# (`sys/nixos-rebuild.nix`), so `sudo reboot` prompted too. Measured, not
# assumed: `pkcheck --action-id org.freedesktop.login1.reboot` returned
# `auth_admin_keep` and `sudo -n true` returned "a password is required". That
# is the whole reason an agent's ability to restart this box looked like a coin
# flip.
#
# Same shape as `rebuild-top`: NOPASSWD on a WRAPPER that takes a fixed verb,
# never on `systemctl`, which is NOPASSWD:ALL wearing a hat.
#
# THE MACHINE HE CANNOT REACH is the design constraint. On 2026-08-26 `top` was
# at home, he was not, and there was nothing else on its LAN — so:
#
#   * `poweroff` needs a literal `--confirm`. Wake-on-LAN (`sys/net/wol.nix`)
#     can only wake it from a machine on its own segment, so with nothing at
#     home a poweroff STRANDS the box until someone walks up to it. That is not
#     a verb an agent should be able to reach for by accident.
#   * `reboot` does not, and needs none. A box that comes back up is the whole
#     point, and this one has a known-good boot ring behind it
#     (`sys/boot-known-good.nix`).
#   * `status` touches nothing, so the entire privileged path can be PROVED
#     without exercising the destructive half of it — which matters when the
#     only other test is a reboot you cannot undo.
#
# THE ESCALATION EXISTS BECAUSE THE CLEAN PATH IS THE ONE THAT HANGS. A box
# wedged badly enough to need a remote reboot is often wedged badly enough that
# `systemctl reboot` blocks on a unit that will never stop. So:
#
#   remote-power reboot           # clean: systemctl reboot
#   remote-power reboot-force     # skip the unit shutdown (systemctl reboot -ff)
#   remote-power reboot-sysrq     # kernel-level: sync, remount read-only, reset
#
# `reboot-sysrq` is the one that still works when userspace is gone, and it is
# the emergency SEQUENCE, not the bare reset — sync (s), remount read-only (u),
# then reboot (b), each with a moment to land. `kernel.sysrq` is raised to 176
# below (sync 16 + remount-ro 32 + reboot 128) because it ships at 16 here, so
# the `b` this depends on was masked and would have failed silently.
#
# NixOS-only, so `book` does not get it — it is a laptop that travels with him
# and is not the machine anyone needs to reach from away.
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
        # Deliberately awkward: with nothing on this box's LAN to wake it, off
        # is a state nobody can get it out of remotely.
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
  # 16 (sync) is the stock value here; `reboot-sysrq` needs remount-ro and
  # reboot too, and a masked bit fails SILENTLY — the write to
  # /proc/sysrq-trigger succeeds and nothing happens.
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
