{ config, lib, ... }:

let
  # Use the Asahi cross package set so top builds book's kernel.
  asahi = config.hardware.asahi.pkgs;
  base = asahi.linux-asahi.override {
    _kernelPatches = config.boot.kernelPatches;
  };
  kernel = base.kernel.override {
    buildLinux = args: asahi.buildLinux (args // {
      pname = "linux-asahi-fairydust";
      version = "7.3.4";
      modDirVersion = "7.3.4";
      extraMeta = args.extraMeta // { branch = "7.3"; };
      src = asahi.fetchFromGitHub {
        owner = "AsahiLinux";
        repo = "linux";
        rev = "59b64a2cbf154b4315f300d1128a5aeb4616d010";
        hash = "sha256-tycMvapqRpeN0yY/Wr4nQ0V5GlIgvT9o2TTMF3itxuM=";
      };
    });
  };
in
{
  # Fairydust's M1 Air device tree routes DP Alt Mode through typec1:
  # the left-front USB-C port (nearest the trackpad). The Asahi boot module
  # takes matching device trees from this kernel for m1n1 and U-Boot.
  boot.kernelPackages = lib.mkForce (asahi.linuxPackagesFor kernel);

  boot.kernelPatches = [{
    name = "fairydust-displayport";
    patch = null;
    structuredExtraConfig = with lib.kernel; {
      DRM_APPLE = module;
      PHY_APPLE_ATC = module;
      MUX_APPLE_DPXBAR = module;
      TYPEC_DP_ALTMODE = module;
    };
  }];
}
