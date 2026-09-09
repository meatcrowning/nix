{ pkgs, lib, host, ... }:

# book's rebuild wrapper — the standalone-home-manager twin of `rebuild-top`
# (sys/nixos-rebuild.nix). No root and no NOPASSWD rule involved here; the
# point is that the wrapper itself owns the two rituals agents used to have
# to remember:
#   * the SHARED rebuild lock, at the same canonical path both hosts (and
#     the agents that predate this wrapper) already use. Created
#     world-writable so root- and user-run rebuilds can both open it.
#   * tools/preflight.sh first — its `nix eval` of the top system gates
#     book's config indirectly (one flake), and its other checks are
#     host-neutral. REBUILD_NO_PREFLIGHT=1 skips it deliberately.
# Installed only on `air`: on top the sudo wrapper is the rebuild command.
lib.mkIf (host == "air") {
  home.packages = [
    (pkgs.writeShellScriptBin "rebuild-air" ''
      # book has 7.3 GiB of RAM, shared with its GPU.  Keep one derivation in
      # flight and give its build system four threads: this is the measured
      # no-thrash setting recorded in docs/agents/book-fedora-state.md.  Two
      # simultaneous derivations make their non-compiler memory overlap and
      # are much less predictable under nix-daemon's 5 GiB hard ceiling.
      BUILD_CORES=4
      BUILD_JOBS=1

      REPO=/home/lam/nix
      REV=$(${pkgs.git}/bin/git -C "$REPO" rev-parse HEAD)
      FLAKE="git+file://$REPO?rev=$REV"
      if ! ${pkgs.git}/bin/git -C "$REPO" diff --quiet HEAD -- \
          || [ -n "$(${pkgs.git}/bin/git -C "$REPO" ls-files --others --exclude-standard)" ]; then
        echo "rebuild-air: committed HEAD ''${REV:0:8}; shared working-tree changes are excluded" >&2
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
        echo "rebuild-air: waiting for another rebuild to finish (lock: $LOCK)..." >&2
        if ! ${pkgs.util-linux}/bin/flock -w 600 9; then
          echo "rebuild-air: gave up waiting for the rebuild lock after 600s" >&2
          exit 1
        fi
      fi

      if [ "''${REBUILD_NO_PREFLIGHT:-0}" != 1 ]; then
        if ! PREFLIGHT_FLAKE="$FLAKE" /home/lam/nix/tools/preflight.sh; then
          echo "rebuild-air: preflight FAILED — fix the above, or skip once with REBUILD_NO_PREFLIGHT=1" >&2
          exit 1
        fi
      fi

      # Keep a compact, private record that can be correlated with Nix's
      # per-derivation build logs.  The daemon's cgroup contains the actual
      # builders, unlike this client process, so these are the useful memory
      # readings when a rebuild makes book sluggish.  Nothing is sampled from
      # the desktop session and the sampler ends with the switch.
      STATE_ROOT="''${XDG_STATE_HOME:-/home/lam/.local/state}/nix-builds"
      RUN="$STATE_ROOT/rebuild-air-$(${pkgs.coreutils}/bin/date +%Y%m%dT%H%M%S%z)-$$"
      ${pkgs.coreutils}/bin/mkdir -p "$RUN"
      ${pkgs.coreutils}/bin/chmod 700 "$RUN"
      METRICS="$RUN/metrics.tsv"
      CGROUP=/sys/fs/cgroup/system.slice/nix-daemon.service
      printf 'timestamp\tmemory_current_bytes\tcgroup_lifetime_peak_bytes\tmemory_events\tmem_available_kib\tswap_free_kib\tpsi_full_avg10\ttmp_available_bytes\tnix_store_available_bytes\n' >"$METRICS"
      peak_at_start=$(${pkgs.coreutils}/bin/cat "$CGROUP/memory.peak" 2>/dev/null || printf '?')
      printf 'revision=%s\ncores=%s\nmax_jobs=%s\ncgroup_lifetime_peak_at_start_bytes=%s\n' \
        "$REV" "$BUILD_CORES" "$BUILD_JOBS" "$peak_at_start" >"$RUN/meta"

      sample() {
        now=$(${pkgs.coreutils}/bin/date --iso-8601=seconds)
        current=$(${pkgs.coreutils}/bin/cat "$CGROUP/memory.current" 2>/dev/null || printf '?')
        peak=$(${pkgs.coreutils}/bin/cat "$CGROUP/memory.peak" 2>/dev/null || printf '?')
        events=$(${pkgs.coreutils}/bin/tr '\n' ';' <"$CGROUP/memory.events" 2>/dev/null || printf '?')
        available=$(${pkgs.gawk}/bin/awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)
        swap_free=$(${pkgs.gawk}/bin/awk '/^SwapFree:/ { print $2 }' /proc/meminfo)
        psi=$(${pkgs.gawk}/bin/awk '$1 == "full" { for (i = 1; i <= NF; i++) if ($i ~ /^avg10=/) { sub(/^avg10=/, "", $i); print $i } }' /proc/pressure/memory)
        tmp_available=$(${pkgs.coreutils}/bin/df -B1 /tmp | ${pkgs.gawk}/bin/awk 'NR == 2 { print $4 }')
        store_available=$(${pkgs.coreutils}/bin/df -B1 /nix/store | ${pkgs.gawk}/bin/awk 'NR == 2 { print $4 }')
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
          "$now" "$current" "$peak" "$events" "$available" "$swap_free" \
          "''${psi:-?}" "''${tmp_available:-?}" "''${store_available:-?}" >>"$METRICS"
      }
      sampler() {
        while :; do
          sample
          ${pkgs.coreutils}/bin/sleep 2
        done
      }
      sampler &
      SAMPLER_PID=$!
      stop_sampler() {
        ${pkgs.coreutils}/bin/kill "$SAMPLER_PID" 2>/dev/null || true
        wait "$SAMPLER_PID" 2>/dev/null || true
        sample
      }
      trap stop_sampler EXIT INT TERM

      echo "rebuild-air: ARM work uses one job/four cores; custom cross-builds use top; telemetry: $RUN" >&2
      # The client retains fd 9 (and therefore the lock) for the whole switch.
      set -o pipefail
      home-manager switch --max-jobs "$BUILD_JOBS" --cores "$BUILD_CORES" \
        --print-build-logs --flake "$FLAKE#air" "$@" 2>&1 | ${pkgs.coreutils}/bin/tee "$RUN/build.log"
      result=''${PIPESTATUS[0]}
      sampled_peak=$(${pkgs.gawk}/bin/awk 'NR > 1 && $2 ~ /^[0-9]+$/ && $2 > peak { peak = $2 } END { print peak + 0 }' "$METRICS")
      printf 'sampled_memory_peak_bytes=%s\nexit=%s\nfinished=%s\n' \
        "$sampled_peak" "$result" "$(${pkgs.coreutils}/bin/date --iso-8601=seconds)" >>"$RUN/meta"
      exit "$result"
    '')
  ];
}
