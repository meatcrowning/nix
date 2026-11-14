{ pkgs, ... }:

# Backport the decoder packages until nixpkgs and nixos-apple-silicon move
# together. The current kernel rejects avd-fw 0.1 (missing firmware config).
{
  nixpkgs.overlays = [ (final: prev: {
    avd-fw = prev.avd-fw.overrideAttrs (old: {
      version = "0.2";
      src = final.fetchFromGitHub {
        owner = "AsahiLinux";
        repo = "avd-fw";
        tag = "v0.2";
        hash = "sha256-ib8vn/PbBNv3BWPuWmRZ+dXEcPuJ21Wl+cynf0WPySc=";
      };
      postPatch = ''
        meson rewrite kwargs set project / version '0.2'
      '';
      # M1 supports H.264, HEVC and VP9; AV1 requires M3 or later.
      mesonFlags = old.mesonFlags ++ [ "-Dvideo-codecs=h264,h265,vp9" ];
    });
  }) ];

  # The pinned upstream module references an absent asahi-va-driver package
  # in its cross package set. Build this small userspace driver natively,
  # against Book's libva/libdrm, and install the same bridge explicitly.
  hardware.graphics.extraPackages = [ (pkgs.stdenv.mkDerivation {
    pname = "asahi-va-driver";
    version = "2.0";
    src = pkgs.fetchFromGitHub {
      owner = "AsahiLinux";
      repo = "asahi-va-driver";
      tag = "2.0";
      hash = "sha256-caIFHEBrgMhxLoXLJCn3JrZPcy3MAox5apXjvy3RxI8=";
    };
    strictDeps = true;
    nativeBuildInputs = with pkgs; [ meson ninja pkg-config ];
    buildInputs = with pkgs; [ libva libdrm linuxHeaders ];
    mesonFlags = [ "-Ddriverdir=${placeholder "out"}/lib/dri" ];
    meta.license = pkgs.lib.licenses.gpl3Plus;
  }) ];
  environment.sessionVariables.LIBVA_DRIVER_NAME = "asahi";
}
