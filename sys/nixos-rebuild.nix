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

    # /tmp/claude-1000 is CLAUDE CODE's own scratch root, not ours — we only
    # borrow a subdirectory of it for the lock. Claude Code refuses to start
    # when it finds that directory owned by another uid ("/tmp/claude-1000 is
    # in use by uid 0") and makes him delete it and log in again. `mkdir -p`
    # here runs as ROOT and used to chmod only the CHILD, leaving the parent
    # root:root 0755 — so on any boot (which empties /tmp) where a rebuild
    # happened before the first `claude`, the next `claude` was locked out.
    # Create the parent as the invoking user, and repair a root-owned one left
    # by an older wrapper.
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

    # A heavy build and a loaded GPU backend never run at the same time —
    # unless he says they may.
    #
    # The freeze on 2026-08-09 was a rebuild that pulled in ollama-cuda — not
    # in any substituter at that revision, so nvcc started compiling ggml's
    # kernels locally — while a ComfyUI video run held the other half of the
    # RAM. sys/nix-build-limits.nix makes that survivable; this makes it not
    # happen, which is better: rationing two heavy jobs against each other just
    # makes both of them bad. An agent has no way to know a one-line nix change
    # means half an hour of nvcc, so the wrapper works it out itself.
    #
    # WHOSE CALL IT IS (2026-08-09, his): not the agent's. The wrapper used to
    # suspend comfy on its own judgement; now a loaded backend in front of a
    # heavy plan raises a CRITICAL toast — "Stop & rebuild" / "Rebuild anyway" —
    # and does what he picks. Silence for the ask timeout is "anyway", because
    # an unattended machine must not sit on the held rebuild lock waiting for a
    # click; that path is the throttled one, which the cgroup caps make safe.
    #
    # BOTH backends count, and "loaded" is not "busy": comfy keeps its weights
    # resident after a run and ollama keeps a model warm for its whole
    # keep_alive, so a backend that is answering nothing at all can still be
    # holding 23 GB. That is the memory the build has to fit around, so warm is
    # reason enough to ask. (A comfy render actually in flight is still never
    # interrupted — on "Stop & rebuild" it is waited out first.)
    #
    # "Heavy" is name-matched against the dry-run plan, because every switch
    # builds a handful of tiny units (etc, system-path, unit-*.drv) and gating
    # on those would mean gating always. The plan costs ~12s of eval, paid only
    # when a backend is actually loaded. Skip the whole thing with
    # REBUILD_IGNORE_GPU=1; REBUILD_ASK_TIMEOUT sets how long the toast waits.
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

    # NOT exec'd, unlike every other path here: the trap above has to survive
    # the switch so comfy comes back whatever happens to it — a failed build, a
    # Ctrl-C, a killed agent. fd 9 stays open in this shell, so the lock is held
    # exactly as long as it was before.
    #
    # ROOT builds in-process, so without this scope the builders would inherit
    # whatever cgroup the caller happened to sit in — a kitty or claude scope,
    # unbounded. The slice is sys/nix-build-limits.nix.
    # $throttle is empty unless we failed to get comfy out of the way — the
    # slice's own ceilings are a backstop, not a tax on every build.
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
