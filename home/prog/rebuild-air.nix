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

      # exec keeps fd 9 (and therefore the lock) held for the whole switch.
      exec home-manager switch --flake "$FLAKE#air" "$@"
    '')
  ];
}
