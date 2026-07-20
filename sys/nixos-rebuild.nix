{ pkgs, ... }:

# Passwordless `nixos-rebuild switch` for lam, so rbsys / rbhome / update never
# prompt for a password. Same NOPASSWD approach as the smartctl / drive-label
# rules in sys/disks.nix (security.sudo.extraRules is a list and merges).
#
# Both the stable /run/current-system symlink and the resolved store path are
# listed, so the rule matches whether or not sudo canonicalises the command to
# its store path. The store path changes on a nixpkgs bump, but the rule is
# rebuilt alongside it, and the in-progress rebuild is authorised by the
# currently-active rule — so `update` keeps working across version bumps.
#
# Trade-off (accepted, single-user desktop): any process running as lam can
# rebuild the system as root without a prompt.
{
  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = [
      { command = "/run/current-system/sw/bin/nixos-rebuild"; options = [ "NOPASSWD" ]; }
      { command = "${pkgs.nixos-rebuild}/bin/nixos-rebuild"; options = [ "NOPASSWD" ]; }
    ];
  }];
}
