{ pkgs, lib, privateConfig, ... }:

# Cross-machine sync for ~/xanadu, the .xu document space (its own private
# repo). Same engine as nix-docs-sync, narrowed by CM_SYNC_PATHS: a tick
# commits only the documents and their edit-time journal, because tool/ in the
# same repo takes hand-made commits and must never be swept up half-edited.
# Those commits still arrive on the other host through the tick's merge.
#
# The repo tracks its own .gitignore/.gitattributes, so CM_SYNC_SEED points
# at a directory that deliberately does not exist and nothing is overwritten.
# The fallback remote lets a host evaluate before its private config gains the
# entry; the engine then reads origin from the existing clone.
{
  systemd.user.services.xanadu-sync = {
    Unit.Description = "Sync ~/xanadu documents across machines";
    Service = {
      Type = "oneshot";
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.git
          pkgs.gh
          pkgs.coreutils
          pkgs.gnused
          pkgs.util-linux
          pkgs.inetutils
        ]}"
        "CM_SYNC_REPO=%h/xanadu"
        "CM_SYNC_REMOTE=${privateConfig.repositories.xanadu or ""}"
        "CM_SYNC_LOG=%h/.cache/xanadu-sync.log"
        "CM_SYNC_SEED=%h/.config/scripts/xanadu-seed-none"
        "CM_SYNC_PATHS=*.xu README.md times"
        "CM_SYNC_LABEL=document"
        "CM_SYNC_MAX_MB=25"
      ];
      ExecStart = "%h/.config/scripts/claude-memory-sync.sh";
    };
  };

  systemd.user.timers.xanadu-sync = {
    Unit.Description = "Periodically sync ~/xanadu documents across machines";
    Timer = {
      OnBootSec = "3min";
      OnStartupSec = "3min";
      OnUnitActiveSec = "5min";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
