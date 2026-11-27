{ config, pkgs, lib, host, ... }:

# Keeps the Saves library (~/Projects/saves/data, see home/prog/saves.nix)
# identical on top and book, whichever host downloaded or changed it. Top
# drives a unison run over SSH every few minutes. Both hosts get the tools:
# book runs the unison server and its own reindex.
#
# The derived index saves.sqlite3 is not synced; each host rebuilds it from the
# synced files (saves-sync-reindex). Host-local caches, logs, locks and
# in-progress downloads stay out. A file changed on both sides is a conflict:
# the merge-listed ones are merged three ways (merge.py), and any other file
# keeps the newer copy.
let
  data = "${config.home.homeDirectory}/Projects/saves/data";
  python = pkgs.python3;
  merge = pkgs.writeScript "saves-sync-merge" ''
    #!${python}/bin/python3
    ${builtins.readFile ./saves-sync-files/merge.py}
  '';
  reindex = pkgs.writeShellApplication {
    name = "saves-sync-reindex";
    runtimeInputs = [ pkgs.coreutils pkgs.findutils ];
    # `saves` comes from the profile (home/prog/saves.nix).
    text = ''
      export PATH="$PATH:${config.home.profileDirectory}/bin"
      ${builtins.readFile ./saves-sync-files/reindex.sh}
    '';
  };
  sync = pkgs.writeShellApplication {
    name = "saves-sync";
    runtimeInputs = [ pkgs.unison pkgs.openssh pkgs.util-linux pkgs.coreutils reindex ];
    text = builtins.readFile ./saves-sync-files/sync.sh;
  };
  listed = "{state.sqlite3,archive.sqlite3}";
  lists = "{*.txt,order.log}";
in
{
  home.packages = [ pkgs.unison reindex ] ++ lib.optional (host == "top") sync;

  home.file.".unison/saves.prf" = lib.mkIf (host == "top") {
    text = ''
      root = ${data}
      root = ssh://book/${data}
      servercmd = ${config.home.profileDirectory}/bin/unison
      batch = true
      auto = true
      prefer = newer
      times = true
      fastcheck = true
      confirmbigdel = true
      # top keeps YouTube media on its HDD through this symlink; book has a
      # plain directory. Abort rather than read a missing mount as deletions.
      follow = Path youtube/media
      mountpoint = youtube/media

      ignore = Name saves.sqlite3
      ignore = Name saves.next.sqlite3
      ignore = Name loudness.sqlite3
      ignore = Name *-lock.sqlite3
      ignore = Name *.sqlite3-journal
      ignore = Name *.sqlite3-wal
      ignore = Name *.sqlite3-shm
      ignore = Name *.log
      ignorenot = Name order.log
      ignore = Name *.part
      ignore = Name *.ytdl
      ignore = Name *.tmp.mp4
      ignore = Path following/_stream

      backupcurrent = Name ${listed}
      backupcurrent = Name ${lists}
      merge = Name ${listed} -> ${merge} sqlite CURRENT1 CURRENT2 CURRENTARCHOPT NEW
      merge = Name ${lists} -> ${merge} lines CURRENT1 CURRENT2 CURRENTARCHOPT NEW
    '';
  };

  systemd.user.services.saves-sync = lib.mkIf (host == "top") {
    Unit.Description = "Sync the Saves library with book";
    Service = {
      Type = "oneshot";
      ExecStart = "${sync}/bin/saves-sync";
      Nice = 10;
      IOSchedulingClass = "idle";
    };
  };

  systemd.user.timers.saves-sync = lib.mkIf (host == "top") {
    Unit.Description = "Sync the Saves library with book every five minutes";
    Timer = {
      OnBootSec = "3min";
      OnUnitActiveSec = "5min";
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
