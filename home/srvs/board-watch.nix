{ pkgs, lib, host, config, ... }:

# Act on his answers to `docs/board.md` without waiting for him to mention them.
#
# The board is where agents park the questions only he can settle. Answering one
# used to do nothing until he next opened a terminal and told a session about
# it; this watches the file and spawns ONE headless agent for ONE newly-answered
# decision. All of the behaviour — the semantic filter, the queue, the failure
# note, the kill switch — is in board-watch-files/board-watch.py; read its
# docstring before changing anything here.
#
# It also MOVES the decision out of NEEDS YOU and into IN FLIGHT as it spawns,
# and hands it back if the agent dies (apps/board/boardmove.py). Two
# consequences for this file: the timer interval below is also the worst-case
# latency for reclaiming an item whose agent was killed outright, since that
# reconcile runs at the top of every tick; and PATH must keep reaching a
# `python3`, because the agent closes the loop with apps/board/tools/boardctl.py
# rather than by editing the markdown (it comes from the per-user profile at the
# end of the list — do not trim that entry).
#
# AND IT CARRIES HIS NOTES. The board app draws a box against every running
# agent (apps/board/boardagents.py). An agent's stdin is closed, so a message is
# a file: the spawned agent is told to poll `boardctl.py inbox take`, and
# anything nobody reads is swept into a queue that a tick of this script works
# with an agent of its own. Third consequence for this file, after the two
# below: the timer interval is also the worst case for a note he typed while
# nothing was running, since the queue is only looked at on a tick.
#
# AND IT IS NOW THE ORCHESTRATOR. The board app grew ONE box at the top of the
# window — free text, enter, into that same inbox — because he asked for a
# control surface rather than a per-agent chat: "a single box that i could type
# things into, press enter, and have them sent to an inbox. then an agent
# figures out what agents to assign to what". The run this unit starts for that
# input no longer does the work itself. It PLANS: it splits the input up and
# either dispatches worker agents (detached, capped, drawn as cards on his
# board) or asks him a question in NEEDS YOU. apps/board/boardwork.py is the
# mechanism, the cap and both prompts.
#
# Two consequences for this file, and they are why it changed:
#   - a third trigger, `board-inbox.path` below, so typing into that box does
#     not wait up to five minutes for the timer;
#   - a tick now also PROMOTES work that was dispatched above the concurrency
#     cap, so the timer interval is the worst case for a queued task starting
#     once a slot frees — the same guarantee reconcile() and sweep() already
#     gave stranded items and unread notes.
#
# BOTH MACHINES, and the duplicate is prevented by AFFINITY rather than by a
# gate. This was `top`-only until 2026-07-29 — `home/` is shared verbatim with
# `air`/book and docs/ syncs both ways every five minutes, so deploying it to
# both would have had one answer picked up twice, by two agents, on two
# checkouts of the same two repos. The cost of that gate was that answering on
# book did nothing at all until he was next sitting at top, which is not what he
# asked for. So instead:
#
#   * A DECISION is stamped with the machine he answered it on — an HTML comment
#     the parser owns (`boardparse.set_answer_host`, written by the board app in
#     the same targeted line edit as the answer). `board-watch.py`'s `owns()`
#     fires only on its own host's stamp; an unstamped one (a hand edit, or an
#     answer predating the stamp) belongs to `top`, the machine that is always
#     on. Re-answering an item on the other machine restamps it and is therefore
#     the hand-off. There is no automatic takeover, on purpose: a claim would
#     have to live in a file that syncs every five minutes, and a five-minute
#     window in which both machines believe they own an item is the very
#     duplicate this is preventing.
#   * TYPED INPUT needs no rule at all. The inbox lives under
#     `~/.local/state/board/`, which nothing syncs, so a sentence exists only on
#     the machine it was typed on and is worked there. Same for the worker
#     queue, the cap, the watcher's fingerprints and the kill switch.
#
# On book this is a systemd USER unit under standalone home-manager on Fedora —
# no `sys/` involved, nothing NixOS-specific. `systemd.user.startServices`
# defaults to true (home-manager 25.05+), so `home-manager switch --flake
# ~/nix#air` reloads the manager and starts these three units itself.
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
  xdg.configFile."scripts/board-watch.py" = {
    source = ./board-watch-files/board-watch.py;
    executable = true;
  };

  systemd.user.services.board-watch = {
    Unit = {
      Description = "Work one newly-answered decision from ~/nix/docs/board.md";
      # THE OUTER NET, and it is set this high on purpose. The path units
      # retrigger in bursts (his edit, then the sync's pull of it, then the
      # agent's own commit, then the timer) and every run is cheap when there is
      # nothing new, so the default 5-starts-in-10s would wedge the unit for the
      # rest of the session over normal traffic — which is why this used to be
      # 0, i.e. off entirely.
      #
      # Off entirely turned out to be worse. On 2026-07-28 a bug in the script
      # made every run return before draining the app's inbox queue, and
      # `board-inbox.path` below is level-triggered: 3,151 starts in a few
      # minutes on the machine he was sitting at. The script now backs itself
      # off (`spin_guard`), and that is the guard that matters because it cannot
      # wedge anything; this exists for the runaway the script cannot see — a
      # crash on import, a broken PATH — where nothing in Python ever runs.
      #
      # 30 a minute is far above any legitimate burst and far below a loop. If
      # it ever does trip, the unit goes `failed` and SAYS SO on his own board
      # (boardagents.watcher_state reads exactly this unit); recovery is
      # `systemctl --user reset-failed board-watch.service`.
      StartLimitIntervalSec = 60;
      StartLimitBurst = 30;
    };
    Service = {
      Type = "oneshot";
      # BELT AND BRACES FOR THE WORKERS, and it is worth stating why it is only
      # the braces. A oneshot's default KillMode is `control-group`: when the
      # main process exits, systemd kills everything LEFT IN ITS CGROUP — and a
      # child detached with `start_new_session` is still in that cgroup, because
      # that call detaches the process GROUP (a terminal-signal concept) and says
      # nothing about cgroups. So every worker an orchestrator dispatched was
      # killed seconds later, while the board honestly reported the work as
      # dispatched and in hand. Measured on top 2026-07-29: worker `we9f99c`
      # registered at 22:49:16, the orchestrator exited at 22:49:29, and the
      # worker's transcript ends three tool calls in.
      #
      # The real fix is in `apps/board/boardwork.py`, which now asks the user
      # manager for one transient unit per worker (`systemd-run --user
      # --unit=board-worker-<id>`) — its own cgroup, a real lifecycle, the
      # 45-minute cap actually enforced, and a genuine systemd unit, which is
      # the shape he asked for the agents section in. That path needs no
      # rebuild, which is why it is the primary one.
      #
      # This line covers the fallback: on a machine with no user manager (or
      # with `BOARD_WORK_NO_UNIT=1`) `boardwork` still spawns a plain detached
      # child, and without this that child dies with the tick. Both were
      # measured to survive; this one only takes effect after a rebuild.
      KillMode = "process";
      # Pinned, because the ambient systemd-user PATH cannot be relied on for
      # any of these: claude is the agent; git/gh are what it commits and pushes
      # with (the credential helper is `!gh auth git-credential`); hyprctl and
      # quickshell answer the at-the-machine gate; coreutils/util-linux supply
      # date and flock. `bash` and `openssh` are here for the agent's own use,
      # not the watcher's.
      #
      # THE TAIL HAS TO NAME BOTH MACHINES' PROFILE LAYOUTS, since this now
      # deploys to book as well and `claude`, `python3`, `hyprctl` and `qs` all
      # come out of a profile rather than out of this list:
      #   ~/.nix-profile/bin              standalone home-manager (book)
      #   /etc/profiles/per-user/lam/bin  home-manager as a NixOS module (top)
      #   /run/current-system/sw/bin      NixOS system packages (top)
      #   /usr/bin:/bin                   Fedora (book) — and where book's
      #                                   systemctl/loginctl/systemd-run come
      #                                   from, deliberately: they must match
      #                                   the user manager that is actually
      #                                   running, which on Fedora is Fedora's.
      #                                   Hence `pkgs.systemd` is top-only.
      # NOT `%h`: systemd expands specifiers in ExecStart but NOT in
      # Environment= (measured on top with a scratch transient unit — the value
      # arrived as the literal `%h/x`), so this interpolates the real path.
      Environment = [
        "PATH=${lib.makeBinPath ([
          pkgs.coreutils
          pkgs.util-linux
          pkgs.bash
          pkgs.git
          pkgs.gh
          pkgs.openssh
          pkgs.nix
        ] ++ lib.optional (host == "top") pkgs.systemd)}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
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
      # Also the unlock latency: an answer that arrived while the screen was
      # locked waits at most this long after he comes back. Matched to the docs
      # sync so a pull from book and the run that acts on it stay adjacent.
      OnUnitActiveSec = "5min";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
