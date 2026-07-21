{ config, ... }:

{
  # The Vista .wav files (Microsoft's — this repo is public) live in a SEPARATE
  # PRIVATE repo, github.com/meatcrowning/vista-sounds, pulled in here as the
  # `sounds/` git submodule. This out-of-store symlink exposes that checkout at
  # the runtime path every consumer expects (~/.local/share/sounds/vista), so
  # the sounds ride along with `git pull --recurse-submodules` on every machine
  # (top and air/book) without the wavs ever landing in this public tree.
  # It's a live symlink, so pulling new sounds needs no rebuild.
  # Full event map: quickshell-files/Sounds.qml.
  home.file.".local/share/sounds/vista".source =
    config.lib.file.mkOutOfStoreSymlink "/home/lam/nix/sounds";

  # Vista "Recycle" crumple whenever the trash contents change (delete to
  # trash / empty trash) — a path unit watching the Trash dir, same pattern
  # as the wal watchers.
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
