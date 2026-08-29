{ pkgs, ... }:

# "Open With…" on a folder Dolphin is showing over sftp://.
#
# KIO can stage a remote FILE into /tmp for an app that only speaks paths; it
# cannot do that for a directory. So on sftp:// the Open With menu offers only
# apps declaring X-KDE-Protocols=sftp — none here — and every local program is
# unreachable. The service menu below sshfs-mounts the host once (under
# ~/mnt/sftp/<user@host>), rewrites the URL to the path inside that mount, and
# launches whatever the user picks on the ordinary local directory.
#
# Both machines: the menu costs nothing where no sftp place exists, and top can
# browse book (or anything else) the same way.

let
  sftpOpenWith = pkgs.writeScriptBin "sftp-openwith" ''
    #!${pkgs.python3}/bin/python3
    ${builtins.readFile ./sftp-openwith-files/sftp-openwith.py}
  '';
in
{
  home.packages = [ sftpOpenWith ];

  # KF6 service menus are Type=Application in kio/servicemenus/. X-KDE-Protocols
  # is what makes it appear on remote items at all; without it KFileItemActions
  # hides the entry the moment the item is not local.
  home.file.".local/share/kio/servicemenus/sftp-openwith.desktop".text = ''
    [Desktop Entry]
    Type=Application
    NoDisplay=true
    MimeType=inode/directory;
    X-KDE-Protocols=sftp
    X-KDE-ServiceTypes=KonqPopupMenu/Plugin
    X-KDE-Priority=TopLevel
    Actions=sftpOpenWith;

    [Desktop Action sftpOpenWith]
    Name=Open With…
    Icon=system-run
    Exec=${sftpOpenWith}/bin/sftp-openwith %U
  '';
}
