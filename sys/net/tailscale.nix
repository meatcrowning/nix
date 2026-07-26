{ ... }:

# Tailscale, so book can reach top when it is NOT on the home LAN. Every
# LAN-facing hole on this box (share.nix) is scoped to enp12s0 and stays that
# way; the tailnet is its own interface and its own trust decision:
#
#   * peers on tailscale0 are machines that authenticated to OUR tailnet —
#     it is not "the internet", so trust it like the wired LAN. This is what
#     lets ssh (dbsync) and SMB (the aud share) work from anywhere.
#   * nothing about this opens a WAN port: tailscaled dials OUT and
#     hole-punches; openFirewall just unblocks its UDP port (41641) so LAN /
#     direct paths skip the DERP relays.
#
# `--operator=lam` lets lam drive the daemon (`tailscale up`/`status`) without
# sudo — which is also what lets an agent finish setup over ssh, since the
# NOPASSWD rule covers only rebuild-top.
{
  services.tailscale = {
    enable = true;
    openFirewall = true;
    extraSetFlags = [ "--operator=lam" ];
  };

  networking.firewall.trustedInterfaces = [ "tailscale0" ];
}
