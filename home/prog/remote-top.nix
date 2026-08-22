{ lib, pkgs, host, ... }:

# book only: top's whole filesystem, browsable from Dolphin.
#
# Two surfaces, because KDE keeps them in different stores and only one of them
# is the sidebar:
#
#   * `remote:/` ("Network" -> Remote Folders) reads $XDG_DATA_HOME/remoteview/
#     for `Type=Link` .desktop files — the same store knetattach's "Add Network
#     Folder" wizard writes. That is the literal "remote folder" entry.
#   * the Dolphin/file-dialog SIDEBAR reads user-places.xbel, which is a
#     different file and does NOT pick up remoteview entries. A place has to be
#     added there separately or it never appears in the sidebar at all.
#
# sftp:// and not smb://: port 22 is already open on tailscale0
# (sys/net/tailscale.nix) so this works off the home LAN, whereas the only SMB
# export top has is the music library (sys/net/share.nix) — /aud, not /. No new
# listener, no new firewall hole, nothing to add on top's side.
#
# It authenticates as `lam` over the existing key, so it is top's filesystem
# with lam's permissions: readable nearly everywhere (/etc, /nix, /home), writable
# where lam already can write. It is NOT uid 0 — top sets `PermitRootLogin no`
# and `PasswordAuthentication no`, and changing that would mean exposing root
# login over the tailnet, which is a deliberate security decision nobody has
# taken. Editing top's system files still means ssh + `sudo -A` there.
#
# The KIO sftp worker is libssh, not OpenSSH, so it does not read ~/.ssh/config:
# the URL names `top` because tailscale MagicDNS resolves it (verified:
# `getent hosts top` -> 100.79.185.101). Do not switch it to `top.local` — that
# is mDNS and answers only at home, which is the bug this whole path exists to
# avoid.
#
# Not on top, which would only be pointing at itself. If book ever needs to be
# reachable the same way it needs an sshd first; Fedora's is not enabled here.
lib.mkIf (host == "air") {
  # The Remote Folders entry. Same four keys knetattach writes; verified to
  # appear with `kioclient ls remote:/`.
  home.file.".local/share/remoteview/top-root.desktop".text = ''
    [Desktop Entry]
    Type=Link
    Name=top (/)
    Icon=folder-remote
    URL=sftp://top/
  '';

  # The sidebar place. user-places.xbel is live KDE state — Dolphin rewrites it
  # whenever a place is added, reordered or hidden — so this can NOT be a
  # home.file symlink into the store: that would make the sidebar read-only and
  # every reorder fail. Insert once, by hand, and leave the rest of the file
  # byte-for-byte alone.
  #
  # Text insertion before the final </xbel> rather than an XML round-trip: KDE
  # writes three namespace prefixes into the root element, and reserialising
  # through ElementTree renames them (ns0:, ns1:) and drops the DOCTYPE, which
  # KFilePlacesModel then reads as an empty places list — i.e. it would wipe the
  # sidebar. Appending text cannot do that.
  #
  # KFilePlacesModel groups by URL scheme, so an sftp:// bookmark lands under
  # "Remote" with no extra metadata. KDirWatch picks the change up live; a
  # running Dolphin does not need restarting.
  home.activation.dolphinPlaceTop = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    ${pkgs.python3}/bin/python3 ${./remote-top-files/add-place.py} || true
  '';
}
