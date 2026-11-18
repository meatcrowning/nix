{ user, ... }:

{
  # Keep top's absolute track paths valid on book without copying the library.
  # Credentials remain host-local runtime state, outside the Nix store.
  fileSystems."/run/media/lam/SSD/aud" = {
    device = "//top/aud";
    fsType = "cifs";
    options = [
      "noauto" "nofail" "_netdev" "x-systemd.automount"
      "x-systemd.mount-timeout=5s" "x-systemd.idle-timeout=1min"
      "uid=1000" "gid=100" "credentials=/home/${user}/.smbcred"
      "iocharset=utf8" "vers=3.1.1" "cache=loose" "actimeo=30"
    ];
  };

  # Player repairs stale SMB sessions after suspend by restarting this mount.
  security.polkit.extraConfig = ''
    polkit.addRule(function(action, subject) {
      if (action.id == "org.freedesktop.systemd1.manage-units" &&
          action.lookup("unit") == "run-media-lam-SSD-aud.mount" &&
          action.lookup("verb") == "restart" &&
          subject.user == "${user}" && subject.local && subject.active) {
        return polkit.Result.YES;
      }
    });
  '';
}
