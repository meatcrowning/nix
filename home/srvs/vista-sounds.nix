{ ... }:

{
  # Vista "Recycle" crumple whenever the trash contents change (delete to
  # trash / empty trash) — a path unit watching the Trash dir, same pattern
  # as the wal watchers. The sound files themselves live UNTRACKED in
  # ~/.local/share/sounds/vista (they're Microsoft's; this repo is public).
  # Full event map: quickshell-files/Sounds.qml.
  systemd.user.services.vista-trash-sound = {
    Unit.Description = "Play the Vista recycle sound when the trash changes";
    Service = {
      Type = "oneshot";
      ExecStart = ''/bin/sh -c 'exec pw-play "$HOME/.local/share/sounds/vista/Windows Recycle.wav"' '';
    };
  };
  systemd.user.paths.vista-trash-sound = {
    Unit.Description = "Watch the trash directory for the Vista recycle sound";
    Path.PathChanged = "%h/.local/share/Trash/files";
    Install.WantedBy = [ "default.target" ];
  };
}
