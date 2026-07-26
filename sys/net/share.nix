{ config, lib, pkgs, ... }:

# Serve the music library to `air` over SMB, LAN-only.
#
# The whole design of docs/air-library-share.md rests on ONE invariant: air
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
        "hosts allow" = "${lanCidr} 127.0.0.1";
        "hosts deny" = "0.0.0.0/0";
        # SMB3 only, and sign nothing on a wired LAN we control — signing
        # costs real throughput on a 208 GB library and buys nothing here.
        "server min protocol" = "SMB3";
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

  # Samba keeps its OWN password database, seeded once by hand:
  #     sudo smbpasswd -a lam
  # NixOS cannot declare that (it is a secret), so it is a documented one-time
  # step — see the STATUS block in docs/air-library-share.md.

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
