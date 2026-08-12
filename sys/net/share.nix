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
    # which is the modern path. But Symfonium (Android, jcifs-ng) still
    # resolves an SMB server it browses for by NetBIOS name query
    # (UDP 137), not mDNS — with nmbd off there was nothing on the LAN to
    # answer that query, so browsing/resolving `top` from Symfonium failed
    # even though negotiation/auth/RPC were all clean by IP (verified
    # 2026-08-11 over loopback+LAN+tailnet). nmbd on, scoped to the LAN
    # interface exactly like every other hole below — it is a broadcast
    # protocol, so it buys nothing over the tailnet anyway.
    nmbd.enable = true;
    openFirewall = false; # scoped by interface below instead of globally

    settings = {
      global = {
        "workgroup" = "WORKGROUP";
        "server string" = "top";
        "server role" = "standalone server";
        "map to guest" = "never";
        # SMB direct only — drop the legacy NetBIOS session service on 139.
        # nmbd (name service, 137/138) is a separate daemon/ports and stays on
        # for Symfonium's NetBIOS resolution below; smbd itself has no reason
        # to also listen on 139, which was a dead-weight 0.0.0.0 listener
        # (firewall-dropped on the LAN, but reachable from the tailnet, which
        # trusts the whole interface).
        "smb ports" = "445";
        # 100.64.0.0/10 is the tailnet (sys/net/tailscale.nix) — authenticated
        # peers only, so the share works when book is off the home LAN.
        "hosts allow" = "${lanCidr} 100.64.0.0/10 127.0.0.1";
        "hosts deny" = "0.0.0.0/0";
        # SMB2 floor, not SMB3 — but spelled as the EXACT dialect, not the
        # "SMB2" alias. `server min protocol = SMB2` still made smbd flatly
        # refuse a client whose dialect list tops out at bare SMB 2.0.2
        # (`smbclient` forced to offer only SMB2_02 -> NT_STATUS_NOT_SUPPORTED
        # at negotiation, verified live 2026-08-11 both directly against smbd
        # and against a throwaway smbd instance): the smb.conf(5) manpage
        # says outright "By default SMB2 selects the SMB2_10 variant", so the
        # bare "SMB2" alias floors at 2.1, not 2.0.2. jcifs-ng (Symfonium's
        # backend) offers only the SMB2_02 baseline dialect when SMB3 is off
        # (its default) — so the SMB3->SMB2 change in this file's prior
        # revision changed nothing for it, and "cannot list the content of
        # the folder" was still a negotiation failure at the wire, one rung
        # lower than before. SMB1/NT1 is still refused (real insecurity);
        # SMB2_02 is not, and sign nothing on a wired LAN we control —
        # signing costs real throughput on a 208 GB library and buys nothing
        # here.
        "server min protocol" = "SMB2_02";
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
  # 22 = ssh (dbsync), 5353/udp = mDNS, 137/138/udp = NetBIOS name service +
  # datagram (nmbd, for Symfonium's name resolution — LAN-only, same as
  # everything else here, and useless over the tailnet anyway since it's
  # broadcast-based).
  networking.firewall.interfaces.${lan} = {
    allowedTCPPorts = [ 445 22 ];
    allowedUDPPorts = [ 5353 137 138 ];
  };
}
