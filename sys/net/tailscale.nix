{ ... }:

# Tailscale, so book can reach top when it is NOT on the home LAN. Every
# LAN-facing hole on this box (share.nix) is scoped to enp12s0 and stays that
# way; the tailnet is its own interface and gets the SAME narrow treatment:
#
#   * peers on tailscale0 are machines that authenticated to OUR tailnet, so
#     the two services book actually needs — ssh (dbsync, the art rsync, and
#     the ComfyUI port-forward) and SMB (the aud share) — are opened there and
#     nothing else is. This used to be `trustedInterfaces = [ "tailscale0" ]`,
#     which quietly published EVERY listener on the box to the tailnet: samba's
#     netbios 139, kdeconnect's 1716, and OpenRGB's unauthenticated SDK server
#     on 6742, which listens on 0.0.0.0 and is only saved by the systemd
#     IPAddressDeny in sys/hw/openrgb.nix. An allowlist naming 22 and 445 is
#     the same decision the wired LAN already made; if something else ever
#     needs to be reachable from air, add its port here deliberately.
#   * `--netfilter-mode=off` is what makes that allowlist actually enforced.
#     tailscaled's INPUT hook (`ts-input`) holds an unconditional
#     `-i tailscale0 -j ACCEPT` that runs BEFORE nixos-fw, so with tailscale
#     managing netfilter the allowlist below was dead code and every listener
#     was reachable by any authenticated peer anyway (audited 2026-08-08:
#     3407 pkts on the ts-input accept, 0 on the nixos-fw 22/445 rules). With
#     netfilter off, tailscaled stops installing filter chains and nixos-fw —
#     including this allowlist — governs the interface. tailscaled still manages
#     its own routing table and ip rules, so connectivity is unaffected; it just
#     no longer hijacks the firewall. (Verify end-to-end from book: ssh + smb
#     to top over the tailnet still work. Revert = drop this one flag.)
#   * nothing about this opens a WAN port: tailscaled dials OUT and
#     hole-punches; openFirewall just unblocks its UDP port (41641) so LAN /
#     direct paths skip the DERP relays.
#
# Anything that must stay loopback-only — ComfyUI on 127.0.0.1:8188, driven by
# home/prog/painter.nix — is reached from air over an ssh tunnel instead of
# being rebound. ComfyUI executes arbitrary workflows and reads/writes the
# filesystem; it gets no listener of its own, on any interface.
#
# `--operator=lam` lets lam drive the daemon (`tailscale up`/`status`) without
# sudo — which is also what lets an agent finish setup over ssh, since the
# NOPASSWD rule covers only rebuild-top. It is applied by the upstream
# `tailscaled-set.service` (WantedBy=multi-user.target), NOT by
# `tailscaled-autoconnect.service`, which nixpkgs only defines when an
# authKeyFile is set — so it lands on every boot with no auth key involved.
# Verify with `tailscale debug prefs | grep OperatorUser`.
#
# JOINING THE TAILNET IS INTERACTIVE and cannot be declared here: run
# `tailscale up` (as lam, no sudo) on each machine and open the printed URL,
# logging BOTH into the same account. Afterwards disable key expiry for both
# nodes in the admin console, or the link dies ~180 days later while the user
# is away from home — precisely the case it exists for.
{
  services.tailscale = {
    enable = true;
    openFirewall = true;
    # --netfilter-mode=off: let nixos-fw (below) govern tailscale0 instead of
    # tailscaled's blanket accept. See the note above.
    extraSetFlags = [ "--operator=lam" "--netfilter-mode=off" ];
  };

  # 445 = SMB (the aud share, share.nix), 22 = ssh (dbsync, art rsync, the
  # ComfyUI forward). Deliberately NOT a trusted interface; see above.
  networking.firewall.interfaces."tailscale0".allowedTCPPorts = [ 445 22 ];
}
