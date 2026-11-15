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
  launcher = pkgs.writeShellApplication {
    name = "dwarf-fortress";
    runtimeInputs = [ fexShim pkgs.muvm ];
    # Saves, init and art from the PeridexisErrant pack live as real files in
    # ~/.local/share/df_linux; the nixpkgs wrapper leaves non-symlinks alone.
    text = ''exec muvm -- ${df}/bin/dwarf-fortress "$@"'';
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
