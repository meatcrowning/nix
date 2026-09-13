{ config, pkgs, lib, privateConfig, ... }:

{
  # Scope the public identity to this checkout; unrelated repositories retain
  # their own Git configuration. Apply on both top and book.
  home.activation.publicRepoIdentity = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    repo=${lib.escapeShellArg "${config.home.homeDirectory}/nix"}
    if [ -e "$repo/.git" ]; then
      ${pkgs.git}/bin/git -C "$repo" config --local user.name ${lib.escapeShellArg privateConfig.gitIdentity.name}
      ${pkgs.git}/bin/git -C "$repo" config --local user.email ${lib.escapeShellArg privateConfig.gitIdentity.email}
    fi
  '';
}
