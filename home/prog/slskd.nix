{ config, pkgs, lib, ... }:

{
  # slskd's web API key lives OUTSIDE this repo in ~/.secrets/slskd-api-key
  # (mode 600, untracked) so it never enters git history. The yml is
  # therefore generated at activation time from that file, instead of being
  # a home.file symlink with the key baked into the nix store.
  home.activation.slskdConfig = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    keyFile="$HOME/.secrets/slskd-api-key"
    if [ -f "$keyFile" ]; then
      run mkdir -p "$HOME/.local/share/slskd"
      # home.file used to own this path as a store symlink — replace it.
      [ -L "$HOME/.local/share/slskd/slskd.yml" ] && run rm "$HOME/.local/share/slskd/slskd.yml"
      run sh -c 'printf "web:\n  authentication:\n    api_keys:\n      soul_sync:\n        key: \"%s\"\n        role: Administrator\n" "$(cat '"$keyFile"')" > "$HOME/.local/share/slskd/slskd.yml"'
      run chmod 600 "$HOME/.local/share/slskd/slskd.yml"
    fi
  '';
}
