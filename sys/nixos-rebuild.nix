{ pkgs, ... }:

# Passwordless system rebuild for lam (so rbsys / rbhome / update never prompt),
# but hard-scoped to THIS flake and host. `nixos-rebuild` runs arbitrary code as
# root, so a NOPASSWD rule on the bare `nixos-rebuild` (its old form) was
# effectively NOPASSWD:ALL — any process running as lam could
# `sudo nixos-rebuild switch --flake /tmp/evil#top` (or -I / --override-input /
# --build-host) and get root from a hostile flake, unattended.
#
# Instead we NOPASSWD only a wrapper that hardcodes `switch --flake
# /home/lam/nix#top` and accepts no user-supplied flake/args — just an optional
# literal `--upgrade`. Same wrapper+NOPASSWD approach as drive-label/smartctl in
# sys/disks.nix. The arbitrary-flake -> root path is closed; rbsys/update still
# run without a prompt.
#
# NB: because the bare `nixos-rebuild` NOPASSWD is gone, `sudo nixos-rebuild
# switch ...` now prompts. Agents/humans rebuild via `sudo rebuild-top`
# (passwordless) — or `sudo -A nixos-rebuild ...` for anything the wrapper
# doesn't cover. `nixos-rebuild build` needs no sudo at all.
let
  rebuildTop = pkgs.writeShellScriptBin "rebuild-top" ''
    if [ "$#" -eq 0 ]; then
      exec ${pkgs.nixos-rebuild}/bin/nixos-rebuild switch --flake /home/lam/nix#top
    elif [ "$#" -eq 1 ] && [ "$1" = "--upgrade" ]; then
      exec ${pkgs.nixos-rebuild}/bin/nixos-rebuild switch --upgrade --flake /home/lam/nix#top
    else
      echo "rebuild-top: only an optional '--upgrade' is accepted (flake/host are fixed)" >&2
      exit 2
    fi
  '';
in
{
  # Both the /run/current-system symlink and the resolved store path are listed
  # so the rule matches whether or not sudo canonicalises the invoked command to
  # its store path (mirrors how the old rule listed both).
  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = [
      { command = "/run/current-system/sw/bin/rebuild-top"; options = [ "NOPASSWD" ]; }
      { command = "${rebuildTop}/bin/rebuild-top"; options = [ "NOPASSWD" ]; }
    ];
  }];

  environment.systemPackages = [ rebuildTop ];
}
