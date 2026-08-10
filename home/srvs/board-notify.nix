{ pkgs, lib, host, config, ... }:

# A desktop notification when a spirit's completion lands on this host's
# board (`docs/board.<hostname>.md`).
#
# board-watch (home/srvs/board-watch.nix) closes the loop on the OTHER half of
# the store — a newly ANSWERED decision. This one closes the loop on a worker's
# RESULT: a WAITING ON YOU TO DO bullet tagged COMPLETION (the "done, no errors.
# pushed." record a finishing worker writes — tag being renamed to ENACTED by a
# parallel change, see board-notify.py) fires a toast, unless goetia is already
# the focused window, in which case he is looking at the store and the toast
# would be noise.
#
# NOT A PATH UNIT, and the whole reason this is its own unit with its own
# process: focus. Whether goetia has focus must come from Hyprland's EVENT
# SOCKET, not from `hyprctl activewindow` — that reports CFocusState::window(),
# which rawSurfaceFocus never clears (memory hyprctl-activewindow-lies), so a
# one-shot snapshot would wrongly suppress half the time. The socket only
# pushes on CHANGE and sends no snapshot on connect (measured on top
# 2026-08-01), so the subscription has to be held open by a long-lived process.
# That process IS this service: a simple (persistent) daemon that keeps the
# current focus in memory from the event socket and polls the board for new
# completions. All the behaviour — the tag, the once-per-completion dedupe, the
# focus gate, the seed-first-run, the kill switch — is in
# board-notify-files/board-notify.py; read its docstring before changing
# anything here.
#
# BOTH MACHINES, HOST-NEUTRAL. `home/` is shared verbatim to book, the daemon
# discovers the live Hyprland instance itself (never an inherited
# HYPRLAND_INSTANCE_SIGNATURE — see hypr-env.nix), and `notify-send` comes from
# a nix `libnotify` here. If no compositor answers there is no focus signal, and
# the safe default (fire, don't wrongly suppress) applies — that is deliberate
# and is described in the script. Notifications are harmless when he is locked
# or away, so there is no board-watch at-the-machine gate.
#
# It starts at login via default.target (home-manager systemd.user.startServices
# enables it); if the compositor is not up yet, the daemon just re-discovers
# until it is. `Restart=on-failure` keeps it alive across a transient crash.
# Kill switch: `touch ~/.local/state/board-notify/off`, no rebuild.

# Must run under the board's python: board-notify.py imports the board module set
# (boardparse -> glyphs -> PySide6). Bare pkgs.python3 crash-looped it (Type=simple
# + Restart=on-failure => hundreds of restarts). Same host split as board.nix.
let
  boardPython =
    if host == "top"
    then "${pkgs.python3.withPackages (ps: [ ps.pyside6 ])}/bin/python3"
    else "/usr/bin/python3";
in
{
  xdg.configFile."scripts/board-notify.py" = {
    source = ./board-notify-files/board-notify.py;
    executable = true;
  };

  systemd.user.services.board-notify = {
    Unit.Description = "Toast when a spirit's completion lands on this host's board";
    Service = {
      Type = "simple";
      Restart = "on-failure";
      RestartSec = 3;
      # Pinned PATH for the same reason every other unit here pins it: the
      # ambient systemd-user PATH reaches none of what this needs. `hyprctl`
      # answers the discovery probe (it resolves the live instance, see
      # board-notify.py's discover_event_socket) and comes from a home profile;
      # `notify-send` comes from libnotify below. The profile tail names both
      # machines' layouts because this deploys to book as well:
      #   ~/.nix-profile/bin              standalone home-manager (book)
      #   /etc/profiles/per-user/lam/bin  home-manager as a NixOS module (top)
      #   /run/current-system/sw/bin      NixOS system packages (top)
      #   /usr/bin:/bin                   Fedora (book)
      # NOT `%h`: systemd expands specifiers in ExecStart but NOT in
      # Environment=, so the real home directory is interpolated here.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.util-linux pkgs.libnotify ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = "${boardPython} %h/.config/scripts/board-notify.py";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
