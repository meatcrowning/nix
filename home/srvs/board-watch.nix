{ pkgs, lib, hostProfile, config, ... }:

# Act on answers to this host's board (`docs/board.<hostname>.md`) without
# waiting for him to mention them.
#
# The watcher sees one newly-answered decision, one inbox queue, and one
# orchestrator entry point. The behaviour itself lives in
# `board-watch-files/board-watch.py`; read that docstring before changing
# anything here.
#
# It moves a decision out of NEEDS YOU as it spawns and hands it back if the
# agent dies (`apps/board/boardmove.py`). That makes the timer the worst-case
# latency for reclaiming a dead run, and PATH must still reach `python3`
# because the loop closes through `apps/board/tools/boardctl.py`, not by
# editing the markdown directly.
#
# One board per host since 2026-07-30: `docs/board.top.md` on top,
# `docs/board.book.md` on book. The files still sync as backup/history, but
# only the named host writes its own board. The host stamp below is
# belt-and-braces for restored copies, and `~/.local/state/board/` stays
# machine-local for typed inbox messages, the worker queue, the cap and the
# kill switch.
#
# On book this is a systemd user unit under standalone home-manager; `switch`
# starts it there via `systemd.user.startServices`.
#
# Two triggers are deliberate: `board-inbox.path` catches typed input
# immediately, and the timer drains the queue, promotes over-cap work, and
# re-arms for unlock polling.

let
  # One board per host; the runtime name comes from the OS hostname, not the
  # flake attribute.
  boardHost = hostProfile.hostname;
  boardFile = "%h/nix/docs/board.${boardHost}.md";
  # Use the board Python: the script imports the board module set, so bare
  # pkgs.python3 crashes at import.
  boardPython = hostProfile.boardPython pkgs;
in
{
  xdg.configFile."scripts/board-watch.py" = {
    source = ./board-watch-files/board-watch.py;
    executable = true;
  };

  systemd.user.services.board-watch = {
    Unit = {
      Description = "Work one newly-answered decision from ~/nix/docs/board.${boardHost}.md";
      # Outer guard for bursty retriggers; the script's own spin guard handles
      # the queue loop, this catches the crash-before-Python cases.
      StartLimitIntervalSec = 60;
      StartLimitBurst = 30;
    };
    Service = {
      Type = "oneshot";
      # Fallback only: if a worker is spawned detached instead of as its own
      # unit, keep it alive after the oneshot exits.
      KillMode = "process";
      # Pinned PATH for the watcher and its agent. The tail names both profile
      # layouts, and `%h` is not expanded in Environment=.
      Environment = [
        "PATH=${lib.makeBinPath ([
          pkgs.coreutils
          pkgs.util-linux
          pkgs.bash
          pkgs.git
          pkgs.gh
          pkgs.nix
        ] ++ lib.optionals hostProfile.isTop [ pkgs.systemd pkgs.openssh ])}:/run/wrappers/bin:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:${config.home.homeDirectory}/.local/bin:/usr/bin:/bin"
      ];
      ExecStart = "${boardPython} %h/.config/scripts/board-watch.py";
      # Outer guard only. The script caps the agent itself at 45 minutes so the
      # failure is one it can write onto the board; this is what catches the
      # script wedging somewhere else.
      TimeoutStartSec = "50min";
    };
  };

  systemd.user.paths.board-watch = {
    Unit.Description =
      "Watch ~/nix/docs/board.${boardHost}.md for a newly-answered decision";
    Path.PathChanged = boardFile;
    Install.WantedBy = [ "default.target" ];
  };

  # ...AND the box at the top of the board app. He types a sentence, presses
  # enter, and it becomes a file in `inbox/queue/` (apps/board/boardagents.py) —
  # nothing about board.md changes, so the path unit above cannot see it and the
  # only thing that would pick it up is the five-minute timer. That is the wrong
  # latency for the one control on this desktop that is supposed to feel like
  # typing at somebody.
  #
  # `PathExistsGlob`, not `PathChanged`: the queue is a DIRECTORY OF FILES and
  # what matters is that one exists at all. It is also level-triggered rather
  # than edge-triggered, which is the property that matters here — a message
  # written while the service is already running (the case the docstring records
  # the path unit LOSING for board.md) still fires the moment the run ends,
  # because the file is still sitting there.
  #
  # THE COST OF THAT PROPERTY IS THAT IT LOOPS IF A RUN EVER FAILS TO DRAIN, and
  # "the queue is always drained before the spawn" is exactly the assumption this
  # comment used to make and the script then broke (3,151 starts, above). It is
  # not an assumption any more: there are two guards, `spin_guard()` in the
  # script and the start limit above, and both are documented as being for this.
  systemd.user.paths.board-inbox = {
    Unit.Description = "Watch the board app's inbox for something he typed";
    Path.PathExistsGlob = "%h/.local/state/board/inbox/queue/*.json";
    Path.Unit = "board-watch.service";
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.timers.board-watch = {
    Unit.Description = "Look for board answers the path unit could not deliver";
    Timer = {
      OnBootSec = "4min";
      # Required alongside it: OnBootSec counts from SYSTEM boot but the user
      # manager starts at login, so a login later than 4min after boot leaves
      # the only elapse point in the past and the timer never fires at all.
      # See home/srvs/nix-docs.nix for the 14-hour outage that proved it.
      OnStartupSec = "4min";
      # Also the unlock latency: an answer that arrived while the screen was
      # locked waits at most this long after he comes back. Matched to the docs
      # sync so a pull from book and the run that acts on it stay adjacent.
      OnUnitActiveSec = "5min";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
