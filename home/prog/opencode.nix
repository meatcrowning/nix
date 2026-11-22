{ pkgs, lib, hostProfile, ... }:
let
  launcher = pkgs.writeShellScriptBin "opencode" ''
    export PATH=${lib.makeBinPath [ pkgs.bash pkgs.openssh pkgs.coreutils ]}:$PATH
    case "''${1:-}" in
      --version|-v|--help|-h|completion)
        exec ${pkgs.opencode}/bin/opencode "$@" ;;
    esac
    exec ${lib.optionalString hostProfile.isBook "${pkgs.bash}/bin/bash /home/lam/nix/apps/oracle/tools/ollama-tunnel.sh -- "}${pkgs.python3}/bin/python3 ${./opencode-files/launch.py} \
      ${pkgs.opencode}/bin/opencode "$@"
  '';
in {
  home.packages = [ launcher ];
}
