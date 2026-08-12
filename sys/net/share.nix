{ config, lib, pkgs, ... }:

# Serve the music library to `air` over SMB, LAN-only.
#
# The whole design of docs/agents/air-library-share.md rests on ONE invariant: air
# mounts this share at the SAME absolute path it has here,
# /run/media/lam/SSD/aud. That makes top's library database valid on air
# verbatim — every tracks.path row resolves, so there is no path rewriting and
# no rescan. Do not "simplify" this by exporting a different path.
#
# SMB and not NFS because the library filesystem is exFAT: the kernel exfat
# driver implements no export_operations, so nfsd will most likely refuse to
# export it at all. Samba is userspace and papers over exFAT's absent POSIX
# semantics itself.
#
# Nothing here is exposed beyond the wired LAN: the firewall holes are scoped
# to enp12s0 and the share itself re-checks with `hosts allow`.
let
  lan = "enp12s0";
  lanCidr = "192.168.40.0/24";
in
{
  services.samba = {
    enable = true;
    # netbios name resolution — air finds this host over mDNS (avahi, below),
    # which is the modern path; nmbd is dead weight and another listener.
    nmbd.enable = false;
    openFirewall = false; # scoped by interface below instead of globally

    settings = {
      global = {
        "workgroup" = "WORKGROUP";
        "server string" = "top";
        "server role" = "standalone server";
        "map to guest" = "never";
        # SMB direct only — drop the legacy NetBIOS session service on 139. nmbd
        # is already off, nothing here uses NBT, and 139 was a dead-weight
        # 0.0.0.0 listener (firewall-dropped on the LAN, but reachable from the
        # tailnet, which trusts the whole interface).
        "smb ports" = "445";
        # 100.64.0.0/10 is the tailnet (sys/net/tailscale.nix) — authenticated
        # peers only, so the share works when book is off the home LAN.
        "hosts allow" = "${lanCidr} 100.64.0.0/10 127.0.0.1";
        "hosts deny" = "0.0.0.0/0";
        # SMB2 floor, not SMB3: verified live (2026-08-11) that `server min
        # protocol = SMB3` makes smbd flatly refuse a client whose dialect
        # list tops out at SMB2 (`smbclient -m SMB2` -> NT_STATUS_NOT_SUPPORTED
        # at negotiation, before auth even runs) — and that is exactly what an
        # Android SMB client defaults to (jcifs-ng: SMB3 is "experimental",
        # off unless the app opts in). This was Symfonium's "cannot list the
        # content of the folder": a negotiation failure at the wire, reported
        # by the app as a generic listing error. SMB1/NT1 is still refused
        # (real insecurity); SMB2 is not, and sign nothing on a wired LAN we
        # control — signing costs real throughput on a 208 GB library and buys
        # nothing here.
        "server min protocol" = "SMB2";
        "server smb encrypt" = "off";
        # exFAT has no POSIX attributes to store; asking Samba to emulate them
        # in xattrs it cannot write is a per-file error path, so turn the whole
        # unix-extensions layer off and let the mount's uid/gid do the work.
        "unix extensions" = "no";
        "ea support" = "no";
        "store dos attributes" = "no";
        "map archive" = "no";
        "map readonly" = "no";
        "load printers" = "no";
        "printcap name" = "/dev/null";
        "disable spoolss" = "yes";
      };

      # Read-write: air pushes nothing to the FILES (tag writes stay on top),
      # but the player opens tracks read/write in a couple of paths and a
      # read-only share turns that into an unhelpful error rather than a
      # no-op. The real guardrail is the tagWrites pref, set to "log" on air.
      aud = {
        "path" = "/run/media/lam/SSD/aud";
        "browseable" = "yes";
        "read only" = "no";
        "guest ok" = "no";
        "valid users" = "lam";
        "force user" = "lam";
        "force group" = "users";
      };
    };
  };

  # smbd must not start before the library is actually mounted. The SSD
  # (sys/disks.nix) is `nofail`, so it is NOT part of local-fs.target's
  # requirements and smbd's own ordering lets it win the race — on the
  # 2026-07-26 boot it did: smbd came up at 12:32:38, one second before the
  # exfat mount, logged
  #     canonicalize_connect_path failed for service aud
  # and answered book's reconnect with BAD_NETWORK_NAME. That is not a
  # transient: the client's tcon is dead for good, so the mount on book stayed
  # "active" while every access returned ESTALE, and the player refused to
  # launch. RequiresMountsFor pulls in and orders after the mount unit; if the
  # drive is genuinely absent smbd simply does not run, which is right — `aud`
  # is the only share, and not listening beats listening with no library.
  #
  # Named as the mount UNIT rather than via RequiresMountsFor: upstream's
  # samba.nix already defines that option (for /var/lib/samba) and a second
  # definition is an eval conflict, not a merge. requires+after on
  # run-media-lam-SSD.mount is exactly equivalent for a path inside it.
  systemd.services.samba-smbd = {
    requires = [ "run-media-lam-SSD.mount" ];
    after = [ "run-media-lam-SSD.mount" ];
  };

  # Samba keeps its OWN password database, seeded once by hand:
  #     sudo smbpasswd -a lam
  # NixOS cannot declare that (it is a secret), so it is a documented one-time
  # step — see the STATUS block in docs/agents/air-library-share.md.

  # mDNS: air reaches this host as `top.local` with no DHCP reservation, and
  # keeps working if the address changes.
  services.avahi = {
    enable = true;
    nssmdns4 = true;
    openFirewall = false; # scoped below
    publish = {
      enable = true;
      addresses = true;
      workstation = true;
      userServices = true;
    };
  };

  # air pulls/pushes the metadata database over ssh (player/tools/dbsync.py).
  # Keys only — this is the one service on the box that accepts a login.
  services.openssh = {
    enable = true;
    openFirewall = false; # scoped below
    ports = [ 22 ];
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "no";
    };
  };

  # Every hole is bound to the wired LAN interface, matching the deliberately
  # narrow style of the WiZ rule in hosts/top/configuration.nix. 445 = SMB,
  # 22 = ssh (dbsync), 5353/udp = mDNS.
  networking.firewall.interfaces.${lan} = {
    allowedTCPPorts = [ 445 22 ];
    allowedUDPPorts = [ 5353 ];
  };
}
