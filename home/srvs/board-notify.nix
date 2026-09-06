{ pkgs, lib, hostProfile, config, ... }:

# Toast when a worker completion lands on this host's board.
#
# board-watch covers answered decisions; this covers completed work. The focus
# signal must come from Hyprland's event socket, so this is a persistent daemon
# rather than a path unit. Its behaviour lives in
# `board-notify-files/board-notify.py`.
#
# One code path on both machines: the daemon discovers the live Hyprland
# instance itself, `notify-send` comes from `libnotify`, and the safe default is
# to fire if focus cannot be read. It starts at login, restarts on failure, and
# can be disabled with `touch ~/.local/state/board-notify/off`.

# Use the board Python: the script imports the board module set, so bare
# pkgs.python3 crash-loops it.
let boardPython = hostProfile.boardPython pkgs;
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
      # Pinned PATH for the discovery probe and the toast; `%h` is not expanded
      # in Environment=.
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.util-linux pkgs.libnotify ]}:${hostProfile.profilePathTail config.home.homeDirectory}"
      ];
      ExecStart = "${boardPython} %h/.config/scripts/board-notify.py";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
