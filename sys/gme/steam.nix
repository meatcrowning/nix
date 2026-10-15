{ config, pkgs, ... }:

{
  programs.steam = {
    enable = true;
    package = pkgs.steam.override {
      buildFHSEnv = args: pkgs.buildFHSEnv (args // {
        extraBuildCommands = (args.extraBuildCommands or "") + ''
          # Closure dependencies can bring Unity's read-only Ubuntu config
          # into /etc. The container initializer must generate its own file.
          rm -f "$out/etc/ld.so.conf"
          # Unity's empty resolver file otherwise shadows the host DNS config
          # in Steam and pressure-vessel, causing WebHelper error -105.
          rm -f "$out/etc/resolv.conf"
        '';
      });
    };
    remotePlay.openFirewall = true;
    # dedicatedServer stays closed: hosting a Source dedicated server (27015)
    # isn't something this desktop does, and every steam openFirewall flag opens
    # its ports on ALL interfaces (incl. tailscale0), unlike the rest of the box.
    dedicatedServer.openFirewall = false;
    localNetworkGameTransfers.openFirewall = true;
  };
}
