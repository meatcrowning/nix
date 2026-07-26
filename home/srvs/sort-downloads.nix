{ pkgs, lib, ... }:

# Keep ~/Downloads from silting up with media: images get filed into ~/Pictures,
# videos into ~/Videos. Everything else (installers, archives, model weights,
# extracted game directories) is left exactly where it landed.
#
# Two triggers, because neither is sufficient alone:
#   - sort-downloads.path fires on any change to ~/Downloads, so a fresh
#     download is filed shortly after it finishes
#   - sort-downloads.timer is the backstop for files that arrived while logged
#     out, and for files that were still inside the script's settle window when
#     the path unit fired (the path unit gets no second event once the download
#     has finished writing)
#
# The interesting logic — settle window, partial-download extensions, collision
# suffixes — is in the script; read its header before changing behaviour.

{
  xdg.configFile."scripts/sort-downloads.sh" = {
    source = ./sort-downloads-files/sort-downloads.sh;
    executable = true;
  };

  systemd.user.services.sort-downloads = {
    Unit.Description = "File finished image/video downloads into ~/Pictures and ~/Videos";
    Service = {
      Type = "oneshot";
      # Pinned so the unit doesn't depend on the ambient systemd-user PATH;
      # lsof is the open-file check the script degrades gracefully without.
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.coreutils
          pkgs.lsof
        ]}"
      ];
      ExecStart = "${pkgs.bash}/bin/bash %h/.config/scripts/sort-downloads.sh";
    };
  };

  systemd.user.paths.sort-downloads = {
    Unit.Description = "Watch ~/Downloads for new media to file away";
    Path.PathModified = "%h/Downloads";
    Install.WantedBy = [ "default.target" ];
  };

  systemd.user.timers.sort-downloads = {
    Unit.Description = "Periodically file media out of ~/Downloads";
    Timer = {
      OnBootSec = "3min";
      OnUnitActiveSec = "15min";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
