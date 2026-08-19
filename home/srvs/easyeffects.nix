{ config, pkgs, ... }:

{
  # EasyEffects is stock again as of 8.2.8: the per-channel local-server IPC
  # (wwmm/easyeffects 76a3f9a5) the panel EQ needs is upstream now, so the
  # flake.nix overlay that used to backport it is gone. That socket call —
  #
  #   set_property:output:equalizer:0:left:band2Gain:-3.0
  #
  # — is what the panel probes for before enabling live-edit; a nixpkgs
  # downgrade below 8.2.8 makes the panel EQ read-only again.
  services.easyeffects.enable = true;
}
