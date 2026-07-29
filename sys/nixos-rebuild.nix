{ pkgs, ... }:

# Passwordless system rebuild for lam (so rbsys / rbhome / update never prompt),
# but hard-scoped to THIS flake and host. `nixos-rebuild` runs arbitrary code as
# root, so a NOPASSWD rule on the bare `nixos-rebuild` (its old form) was
# effectively NOPASSWD:ALL — any process running as lam could
# `sudo nixos-rebuild switch --flake /tmp/evil#top` (or -I / --override-input /
# --build-host) and get root from a hostile flake, unattended.
#
# Instead we NOPASSWD only a wrapper that hardcodes `switch --flake
# /home/lam/nix#top` and accepts no user-supplied flake/args — just an optional
# literal `--upgrade`. Same wrapper+NOPASSWD approach as drive-label/smartctl in
# sys/disks.nix. The arbitrary-flake -> root path is closed; rbsys/update still
# run without a prompt.
#
# NB: because the bare `nixos-rebuild` NOPASSWD is gone, `sudo nixos-rebuild
# switch ...` now prompts. Agents/humans rebuild via `sudo rebuild-top`
# (passwordless) — or `sudo -A nixos-rebuild ...` for anything the wrapper
# doesn't cover. `nixos-rebuild build` needs no sudo at all.
let
  # The wrapper also owns the two rituals every agent used to have to remember:
  #   * the SHARED rebuild lock (/tmp/claude-1000/-home-lam-nix/rebuild.lock) —
  #     several agents rebuild this one checkout concurrently; the canonical
  #     path predates this wrapper and existing agents flock it by hand, so it
  #     must not move. Created world-writable because root and user callers
  #     both need to open it (a user cannot open a root-owned 644 lock).
  #   * tools/preflight.sh, run as the INVOKING user via runuser — it checks
  #     the systemd *user* manager and git state, both wrong as root. Skip it
  #     deliberately with REBUILD_NO_PREFLIGHT=1 (e.g. when preflight itself
  #     is what you are debugging); it is skipped with a warning, not a
  #     failure, when SUDO_USER/runuser are unavailable.
  # rebuild-air (home/prog/rebuild-air.nix) is the book-side twin.
  rebuildTop = pkgs.writeShellScriptBin "rebuild-top" ''
    if [ "$#" -eq 1 ] && [ "$1" = "--upgrade" ]; then
      upgrade=1
    elif [ "$#" -ne 0 ]; then
      echo "rebuild-top: only an optional '--upgrade' is accepted (flake/host are fixed)" >&2
      exit 2
    else
      upgrade=0
    fi

    LOCKDIR=/tmp/claude-1000/-home-lam-nix
    LOCK=$LOCKDIR/rebuild.lock
    if [ ! -d "$LOCKDIR" ]; then
      mkdir -p "$LOCKDIR" && chmod 1777 "$LOCKDIR"
    fi
    if [ ! -e "$LOCK" ]; then
      : >"$LOCK" && chmod 666 "$LOCK"
    fi
    exec 9>>"$LOCK"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      echo "rebuild-top: waiting for another rebuild to finish (lock: $LOCK)..." >&2
      if ! ${pkgs.util-linux}/bin/flock -w 600 9; then
        echo "rebuild-top: gave up waiting for the rebuild lock after 600s" >&2
        exit 1
      fi
    fi

    if [ "''${REBUILD_NO_PREFLIGHT:-0}" != 1 ]; then
      if [ -n "''${SUDO_USER:-}" ] && command -v runuser >/dev/null 2>&1; then
        uhome=$(${pkgs.getent}/bin/getent passwd "$SUDO_USER" | cut -d: -f6)
        uid=$(id -u "$SUDO_USER")
        if ! runuser -u "$SUDO_USER" -- env HOME="$uhome" XDG_RUNTIME_DIR="/run/user/$uid" \
             /home/lam/nix/tools/preflight.sh; then
          echo "rebuild-top: preflight FAILED — fix the above, or skip once with REBUILD_NO_PREFLIGHT=1" >&2
          exit 1
        fi
      else
        echo "rebuild-top: WARN: cannot run preflight as the invoking user (SUDO_USER or runuser unavailable) — skipping it" >&2
      fi
    fi

    # exec keeps fd 9 (and therefore the lock) held for the whole switch.
    if [ "$upgrade" = 1 ]; then
      exec ${pkgs.nixos-rebuild}/bin/nixos-rebuild switch --upgrade --flake /home/lam/nix#top
    else
      exec ${pkgs.nixos-rebuild}/bin/nixos-rebuild switch --flake /home/lam/nix#top
    fi
  '';
in
{
  # Both the /run/current-system symlink and the resolved store path are listed
  # so the rule matches whether or not sudo canonicalises the invoked command to
  # its store path (mirrors how the old rule listed both).
  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = [
      { command = "/run/current-system/sw/bin/rebuild-top"; options = [ "NOPASSWD" ]; }
      { command = "${rebuildTop}/bin/rebuild-top"; options = [ "NOPASSWD" ]; }
    ];
  }];

  environment.systemPackages = [ rebuildTop ];
}
