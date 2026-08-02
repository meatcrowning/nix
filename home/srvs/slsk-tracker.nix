{ pkgs, lib, host, ... }:

# A tiny always-on webpage that shows the slskd downloader state at a glance,
# so it never has to be asked for. Serves one self-contained page on
# http://127.0.0.1:5040/ (loopback only -- see ~/nix/AGENTS.md, Off-LAN: nothing
# here opens a listener on a routable interface). The page reads every number
# LIVE on each load -- slskd's loopback API, the missing-track work list, the
# sweep unit's journal, the downloads dir -- and hard-codes nothing; the server
# is a read-only observer that never queues, cancels or mutates a transfer, so
# it can't disturb a download he is listening to. Full rationale and the source
# of each metric are in apps/slsk/tools/dl-tracker.py.
#
# TOP-ONLY, for the same reason soulseek-sweep is (see soulseek-sweep.nix): the
# whole missing-track pipeline -- slskd, the sweep feeder, the spotify-dump work
# list, the aud library it feeds -- lives on `top`. `book` runs none of it, so a
# tracker there would watch an empty stack. Gated on the host module arg rather
# than left to silently no-op: on `book` the unit is simply not present.

lib.mkIf (host == "top") {
  systemd.user.services.slsk-tracker = {
    Unit = {
      Description = "Localhost webpage tracking the slskd downloader state";
      # A crash must not permanently give up (the page would 404 until the next
      # login): disable the start-rate limit so Restart below retries forever.
      StartLimitIntervalSec = 0;
    };
    Service = {
      Type = "simple";
      # Pinned so it doesn't lean on the ambient systemd-user PATH. python3 runs
      # the stdlib server; systemd supplies systemctl (unit health) and
      # journalctl (the sweep import-failure count); coreutils supplies the rest.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.python3 pkgs.systemd pkgs.coreutils ]}"
        "PYTHONUNBUFFERED=1"
      ];
      ExecStart = "${pkgs.python3}/bin/python3 %h/nix/apps/slsk/tools/dl-tracker.py";
      Restart = "on-failure";
      RestartSec = "10s";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
