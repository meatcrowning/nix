{ pkgs, ... }:

# Passwordless Samba admin for agents, so the common share-maintenance actions
# (restart/reload the daemons, reload config live, validate smb.conf, set the
# SMB password) don't pop `sudo -A`'s askpass dialog at the user every time.
#
# Same wrapper+NOPASSWD pattern as sys/nixos-rebuild.nix and the drive-label/
# drive-smart pair in sys/disks.nix: NOPASSWD never lands on the raw command
# (`sudo systemctl restart smbd.service` would let anything be appended —
# `sudo systemctl restart anything.service` is not scopable by sudo alone), it
# lands on a `writeShellScriptBin` wrapper that hardcodes the exact command
# and accepts no user-supplied service/user/args. Five narrow wrappers, one
# per action, rather than one wrapper with a dispatch table — each is small
# enough to read in one glance and cannot be argued into running anything but
# what its name says.
#
# The SMB user is hardcoded to "lam" (the only account sys/net/share.nix's
# `sudo smbpasswd -a lam` doc comment ever names) — smb-passwd cannot be
# pointed at a different system user.
let
  sambaRestart = pkgs.writeShellScriptBin "samba-restart" ''
    exec ${pkgs.systemd}/bin/systemctl restart smbd.service nmbd.service
  '';

  sambaReload = pkgs.writeShellScriptBin "samba-reload" ''
    exec ${pkgs.systemd}/bin/systemctl reload smbd.service nmbd.service
  '';

  # Live config reload with no daemon restart (no dropped connections) — SIGHUP
  # via Samba's own RPC control channel rather than systemd's `reload`.
  sambaReloadConfig = pkgs.writeShellScriptBin "samba-reload-config" ''
    exec ${pkgs.samba}/bin/smbcontrol smbd reload-config
  '';

  # `-s`: skip the "Press enter to see a dump of your service definitions"
  # interactive prompt — just parse smb.conf and report errors.
  smbTestparm = pkgs.writeShellScriptBin "smb-testparm" ''
    exec ${pkgs.samba}/bin/testparm -s
  '';

  # `-s -a lam`: add-or-update the Samba password for the fixed user "lam",
  # reading the new password twice from stdin instead of prompting a TTY —
  # the username is not a parameter, so this cannot touch any other account.
  smbPasswd = pkgs.writeShellScriptBin "smb-passwd" ''
    exec ${pkgs.samba}/bin/smbpasswd -s -a lam
  '';

  wrappers = [
    { name = "samba-restart"; pkg = sambaRestart; }
    { name = "samba-reload"; pkg = sambaReload; }
    { name = "samba-reload-config"; pkg = sambaReloadConfig; }
    { name = "smb-testparm"; pkg = smbTestparm; }
    { name = "smb-passwd"; pkg = smbPasswd; }
  ];

  # Both the /run/current-system symlink and the resolved store path, exactly
  # like sys/nixos-rebuild.nix — sudo may match either depending on whether it
  # canonicalises the invoked command.
  rule = w: [
    { command = "/run/current-system/sw/bin/${w.name}"; options = [ "NOPASSWD" ]; }
    { command = "${w.pkg}/bin/${w.name}"; options = [ "NOPASSWD" ]; }
  ];
in
{
  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = builtins.concatMap rule wrappers;
  }];

  environment.systemPackages = map (w: w.pkg) wrappers;
}
