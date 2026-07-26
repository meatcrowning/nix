{ ... }:

{
  # hardware.openrgb.enable (hosts/top/configuration.nix) starts the SDK server
  # as root listening on 0.0.0.0:6742 with no authentication. The firewall keeps
  # the LAN out, but any local process could still drive a root daemon that
  # writes SMBus/I2C. The only intended client is local (wal-set.sh step 6c /
  # rgb-set.py over 127.0.0.1), so pin the listener to loopback at the systemd
  # level — IP-level filtering, doesn't touch the /dev i2c access it needs.
  systemd.services.openrgb.serviceConfig = {
    IPAddressDeny = "any";
    IPAddressAllow = "localhost";
  };
}
