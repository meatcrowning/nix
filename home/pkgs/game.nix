{ pkgs, lib, ... }:

let
  cga8x8thick = pkgs.fetchurl {
    url = "https://dwarffortresswiki.org/images/0/0e/CGA8x8thick.png";
    sha256 = "16lhbxqzacdvzp4c9lpy0sjhx773y8013yndhb6h6nl9j0sdp429";
  };

  # A theme is a derivation that provides the tileset in data/art
  my-theme = pkgs.stdenv.mkDerivation {
    name = "cga8x8thick-theme";
    phases = [ "installPhase" ];
    installPhase = ''
      mkdir -p $out/data/art
      cp ${cga8x8thick} $out/data/art/CGA8x8thick.png
    '';
  };
in
{
  # dwarf-fortress-packages is x86_64-only (proprietary binary, no aarch64
  # build) — lib.optionals keeps this whole attribute path from ever being
  # forced on air, not just from being installed.
  home.packages = lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
    (pkgs.dwarf-fortress-packages.dwarf-fortress_0_47_05.override {
      theme = my-theme;
      enableDFHack = true;
      enableTWBT = true;
      enableIntro = false;
      enableFPS = true;
      dfhack = (pkgs.dwarf-fortress-packages.dwarf-fortress_0_47_05.dfhack.override {
        stdenv = pkgs.gcc13Stdenv;
      }).overrideAttrs (old: {
        cmakeFlags = (old.cmakeFlags or [ ]) ++ [ "-DCMAKE_POLICY_VERSION_MINIMUM=3.5" ];
      });
      settings = {
        init = {
          # Required for separate map/UI zoom
          PRINT_MODE = "TWBT";
          GRAPHICS = "YES";
          TRUETYPE = "0";
          # Linear pixel perfect scaling (disables texture filtering)
          TEXTURE_PARAM = "NEAREST";

          FONT = "curses_640x300.png";
          GRAPHICS_FONT = "CGA8x8thick.png";
          FULLFONT = "curses_640x300.png";
          GRAPHICS_FULLFONT = "CGA8x8thick.png";
          WINDOWED = false;
        };
      };
    })
  ];
}
