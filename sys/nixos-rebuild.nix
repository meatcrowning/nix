{ pkgs, ... }:

# Passwordless system rebuild for lam, but hard-scoped to THIS flake and host.
# `nixos-rebuild` runs arbitrary code as root, so bare NOPASSWD would be
# equivalent to `NOPASSWD:ALL`. The wrapper closes that path by hardcoding
# `switch --flake /home/lam/nix#top` and accepting only an optional `--upgrade`
# (same wrapper+NOPASSWD shape as sys/disks.nix).
#
# Because the bare rule is gone, `sudo nixos-rebuild switch ...` now prompts.
# Rebuild via `sudo rebuild-top`, or `sudo -A nixos-rebuild ...` when you need
# something the wrapper does not cover. `nixos-rebuild build` still needs no
# sudo.
let
  # The wrapper also owns the shared rebuild lock and the preflight step.
  # The lock path must stay stable because existing agents already flock it by
  # hand; it is world-writable so root and user callers can open it. Preflight
  # runs as the invoking user because it checks the user manager and git state,
  # not root state. Skip it once with REBUILD_NO_PREFLIGHT=1 when needed.
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

    # `/tmp/claude-1000` is Claude Code's scratch root; we only borrow a
    # subdirectory for the lock. The parent must stay owned the way Claude Code
    # expects, and this block repairs a root-owned one left by an older wrapper.
    CLAUDE_TMP=/tmp/claude-1000
    LOCKDIR=$CLAUDE_TMP/-home-lam-nix
    LOCK=$LOCKDIR/rebuild.lock
    if [ ! -d "$LOCKDIR" ]; then
      mkdir -p "$LOCKDIR" && chmod 1777 "$LOCKDIR"
    fi
    if [ -n "''${SUDO_UID:-}" ] && [ "$(stat -c %u "$CLAUDE_TMP" 2>/dev/null)" = 0 ]; then
      chown "$SUDO_UID:''${SUDO_GID:-$SUDO_UID}" "$CLAUDE_TMP" && chmod 700 "$CLAUDE_TMP"
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

    # Heavy builds and loaded GPU backends do not run together unless he says
    # they may. The wrapper dry-builds to detect locally compiled heavyweight
    # outputs, asks through heavy-gate when a backend is loaded, waits out any
    # render if he chose "stop", and otherwise throttles the switch. Silence is
    # "anyway"; `REBUILD_IGNORE_GPU=1` skips the gate and `REBUILD_ASK_TIMEOUT`
    # sets the wait.
    GATE=/home/lam/nix/tools/heavy-gate.sh
    resume_needed=0
    throttle=
    cleanup() { [ "$resume_needed" = 1 ] && "$GATE" resume; }
    trap cleanup EXIT INT TERM

    if [ "''${REBUILD_IGNORE_GPU:-0}" != 1 ] && [ -x "$GATE" ] && "$GATE" loaded; then
      heavy=$(${pkgs.nixos-rebuild}/bin/nixos-rebuild dry-build --flake /home/lam/nix#top 2>&1 \
        | ${pkgs.gnugrep}/bin/grep -oE '/nix/store/[^ ]*\.drv' \
        | ${pkgs.gnugrep}/bin/grep -Ei 'cuda|cudnn|torch|llama|ollama|hyprland|qtwebengine|chromium|llvm|linux-[0-9]|mesa|blender|rustc|gcc-[0-9]' \
        | head -5 || true)
      if [ -n "$heavy" ]; then
        echo "rebuild-top: this switch compiles locally:" >&2
        printf '  %s\n' "$heavy" >&2
        echo "rebuild-top: backends up: $("$GATE" status)" >&2
        answer=$("$GATE" ask "''${REBUILD_ASK_TIMEOUT:-300}")
        echo "rebuild-top: he answered: $answer" >&2
        if [ "$answer" = stop ]; then
          # A render in flight is waited out, never interrupted. If it is STILL
          # going an hour later we do not suspend and do not wait forever — the
          # build goes ahead beside it, under the cgroup caps.
          if "$GATE" wait 3600 && "$GATE" suspend; then
            resume_needed=1
          else
            throttle="-p MemoryHigh=8G -p MemoryMax=14G -p CPUWeight=20 -p IOWeight=20"
            echo "rebuild-top: could not free the backends after all — building throttled to 8G/14G at a fifth of the CPU and I/O weight" >&2
          fi
        elif [ "$answer" != clear ]; then
          throttle="-p MemoryHigh=8G -p MemoryMax=14G -p CPUWeight=20 -p IOWeight=20"
          echo "rebuild-top: building alongside the backends, throttled to 8G/14G at a fifth of the CPU and I/O weight" >&2
        fi
      fi
    fi

    # Not exec'd: the trap has to survive the switch so the backend is restored
    # on failure, Ctrl-C or kill. Root builds in-process, so this scope keeps
    # the builders out of the caller's cgroup; `sys/nix-build-limits.nix` is the
    # backstop, and `$throttle` is only set when the gate could not clear the
    # way.
    scope="${pkgs.systemd}/bin/systemd-run --scope --quiet --slice=nix-build.slice --collect ''${throttle:-}"
    if [ "$upgrade" = 1 ]; then
      $scope ${pkgs.nixos-rebuild}/bin/nixos-rebuild switch --upgrade --flake /home/lam/nix#top
    else
      $scope ${pkgs.nixos-rebuild}/bin/nixos-rebuild switch --flake /home/lam/nix#top
    fi
    rc=$?
    cleanup; resume_needed=0
    exit $rc
  '';
in
{
  # `sudo` resets the environment, so these vars have to be carried across by
  # name for `REBUILD_IGNORE_GPU=1 sudo rebuild-top` and friends to work.
  security.sudo.extraConfig =
    "Defaults:lam env_keep += \"REBUILD_IGNORE_GPU REBUILD_ASK_TIMEOUT REBUILD_NO_PREFLIGHT\"\n";

  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = [
      { command = "/run/current-system/sw/bin/rebuild-top"; options = [ "NOPASSWD" ]; }
      { command = "${rebuildTop}/bin/rebuild-top"; options = [ "NOPASSWD" ]; }
    ];
  }];

  environment.systemPackages = [ rebuildTop ];
}
