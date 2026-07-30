{ ... }:

# KDE Connect's firewall hole, scoped to the wired LAN — deliberately NOT
# `programs.kdeconnect.enable`.
#
# That NixOS module does exactly two things: it puts `kdeconnect-kde` in
# `environment.systemPackages`, which is redundant here (home/pkgs/desktop/kde.nix
# already installs it for lam on both hosts), and it sets a bare
# `networking.firewall.allowedTCPPortRanges`/`allowedUDPPortRanges` of 1714-1764
# with no opt-out — i.e. on EVERY interface. It has no `openFirewall` option, so
# the only way to scope the hole is not to use the module.
#
# Unscoped is wrong here twice over. sys/net/share.nix binds every LAN-facing
# hole to enp12s0, and sys/net/tailscale.nix makes the tailnet an allowlist of
# 22 and 445 precisely because `trustedInterfaces = [ "tailscale0" ]` had
# published every listener on the box — and that comment names "kdeconnect's
# 1716" as one of the things it exposed. With the module enabled, 1714-1764 was
# published to tailscale0 anyway, by a different route: kdeconnectd's listener
# accepts TLS from anything that can reach the port, and pairing is a prompt on
# this desktop rather than a secret. The phones are LAN devices (neither is on
# the tailnet), so scoping costs nothing that is in use.
#
# 1714-1764/tcp is the connection port range and 1714-1764/udp carries the
# identity broadcasts a device is discovered by; closing the UDP side alone
# breaks discovery, and therefore pairing, and therefore notifications.
#
# NixOS-only, so `top` only: `air` is home-manager over Fedora and its firewall
# is Fedora state this repo cannot write.

let
  # Same wired interface share.nix scopes its holes to; kept in step with it.
  lan = "enp12s0";
  kdeconnectPorts = [{ from = 1714; to = 1764; }];
in
{
  networking.firewall.interfaces.${lan} = {
    allowedTCPPortRanges = kdeconnectPorts;
    allowedUDPPortRanges = kdeconnectPorts;
  };
}
