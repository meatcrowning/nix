{ host, lib, pkgs, ... }:

let
  # DF 0.47.05 ships only for x86_64; book runs the Linux build through muvm
  # (4K-page microVM) + FEX. top's builder produces the x86_64 closure.
  x86 = import pkgs.path { system = "x86_64-linux"; config.allowUnfree = true; };
  df = x86.dwarf-fortress-packages.dwarf-fortress_0_47_05;
  # muvm 0.6.0 looks up `FEXInterpreter`; FEX 2608 renamed it to `FEX`.
  fexShim = pkgs.runCommand "fex-interpreter-shim" { } ''
    mkdir -p $out/bin
    ln -s ${pkgs.fex}/bin/FEX $out/bin/FEXInterpreter
  '';
  # The guest's /run/opengl-driver is the host's aarch64 Mesa, which the x86
  # process cannot load. Point glvnd at x86 Mesa and use llvmpipe.
  # PRINT_MODE:2D segfaults on any window resize (tile_cache_lookup, also
  # natively on x86), so init.txt uses PRINT_MODE:STANDARD, which needs GL.
  mesa = x86.mesa;
  launcher = pkgs.writeShellApplication {
    name = "dwarf-fortress";
    runtimeInputs = [ fexShim pkgs.muvm ];
    # Saves, init and art from the PeridexisErrant pack live as real files in
    # ~/.local/share/df_linux; the nixpkgs wrapper leaves non-symlinks alone.
    text = ''
      exec muvm \
        -e LD_LIBRARY_PATH=${mesa}/lib \
        -e __GLX_VENDOR_LIBRARY_NAME=mesa \
        -e LIBGL_DRIVERS_PATH=${mesa}/lib/dri \
        -e LIBGL_ALWAYS_SOFTWARE=1 \
        -- ${df}/bin/dwarf-fortress "$@"
    '';
  };
in
{
  config = lib.mkIf (host == "air") {
    home.packages = [ launcher ];
    xdg.desktopEntries.dwarf-fortress = {
      name = "Dwarf Fortress";
      exec = "${launcher}/bin/dwarf-fortress";
      icon = "applications-games";
      categories = [ "Game" ];
      terminal = false;
    };
  };
}
