{ pkgs, lib, host, ... }:

# Act on his answers to `docs/board.md` without waiting for him to mention them.
#
# The board is where agents park the questions only he can settle. Answering one
# used to do nothing until he next opened a terminal and told a session about
# it; this watches the file and spawns ONE headless agent for ONE newly-answered
# decision. All of the behaviour — the semantic filter, the queue, the failure
# note, the kill switch — is in board-watch-files/board-watch.py; read its
# docstring before changing anything here.
#
# TOP ONLY, on purpose. `home/` is shared verbatim with `air`/book and docs/
# syncs both ways every five minutes, so deploying this to both machines would
# have the same answer picked up twice, by two agents, on two checkouts of the
# same repo. An answer he types on book still gets worked: it reaches top with
# the next sync tick and fires here, once, when he is next at this machine.
#
# TWO TRIGGERS, and both are needed. Measured on top 2026-07-28 with a scratch
# path unit rather than reasoned about, because `board` writes via temp file +
# `os.replace()` and some watch modes miss a rename entirely:
#   - a `path` unit on the FILE does see the rename. PathChanged fired on three
#     consecutive atomic replaces and on an ordinary append, and did not fire
#     for a sibling file in the same directory — so watching board.md beats
#     watching docs/, which every `git` operation of the sync would rattle.
#   - it does NOT queue. With the service made to run for 8s, three replaces
#     during that window produced exactly one further run: systemd re-arms only
#     on an event that arrives while the unit is inactive. An answer typed while
#     an agent is running would be lost outright.
# Hence the timer as well — the same belt-and-braces pairing sort-downloads.nix
# uses, and here it does double duty: it is also what drains the queue when he
# unlocks, since nothing on this desktop emits an unlock signal we can watch.

{
config = lib.mkIf (host == "top") {
  xdg.configFile."scripts/board-watch.py" = {
    source = ./board-watch-files/board-watch.py;
    executable = true;
  };

  systemd.user.services.board-watch = {
    Unit = {
      Description = "Work one newly-answered decision from ~/nix/docs/board.md";
      # The path unit can retrigger in bursts (his edit, then the sync's pull of
      # it, then the agent's own commit); the default 5-starts-in-10s limit
      # would wedge the unit for the rest of the session. Every run is cheap and
      # idempotent when there is nothing new — a parse and a dict compare.
      StartLimitIntervalSec = 0;
    };
    Service = {
      Type = "oneshot";
      # Pinned, because the ambient systemd-user PATH cannot be relied on for
      # any of these: claude is the agent; git/gh are what it commits and pushes
      # with (the credential helper is `!gh auth git-credential`); hyprctl and
      # quickshell answer the at-the-machine gate; systemd/coreutils/util-linux
      # supply loginctl, date and flock. `bash` and `openssh` are here for the
      # agent's own use, not the watcher's.
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.coreutils
          pkgs.util-linux
          pkgs.systemd
          pkgs.bash
          pkgs.git
          pkgs.gh
          pkgs.openssh
          pkgs.nix
        ]}:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin"
      ];
      ExecStart = "${pkgs.python3}/bin/python3 %h/.config/scripts/board-watch.py";
      # Outer guard only. The script caps the agent itself at 45 minutes so the
      # failure is one it can write onto the board; this is what catches the
      # script wedging somewhere else.
      TimeoutStartSec = "50min";
    };
  };

  systemd.user.paths.board-watch = {
    Unit.Description = "Watch ~/nix/docs/board.md for a newly-answered decision";
    Path.PathChanged = "%h/nix/docs/board.md";
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.timers.board-watch = {
    Unit.Description = "Look for board answers the path unit could not deliver";
    Timer = {
      OnBootSec = "4min";
      # Also the unlock latency: an answer that arrived while the screen was
      # locked waits at most this long after he comes back. Matched to the docs
      # sync so a pull from book and the run that acts on it stay adjacent.
      OnUnitActiveSec = "5min";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
};
}
