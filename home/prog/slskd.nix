{ config, pkgs, lib, ... }:

{
  # slskd's web API key lives OUTSIDE this repo in ~/.secrets/slskd-api-key
  # (mode 600, untracked) so it never enters git history. The yml is
  # therefore generated at activation time from that file, instead of being
  # a home.file symlink with the key baked into the nix store.
  #
  # slskd's web UI defaults to `web.ip_address: 0.0.0.0,[::]` (all interfaces)
  # — the firewall doesn't open its port, but that still leaves it reachable to
  # any other local process/user and to SSRF from a browser. Pin both the HTTP
  # and HTTPS listeners to loopback, and scope the Administrator key's CIDR to
  # loopback too, so it can't be presented from anywhere but this box.
  # (Key names/structure per slskd's slskd.example.yml `web:` block.)
  home.activation.slskdConfig = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    keyFile="$HOME/.secrets/slskd-api-key"
    if [ -f "$keyFile" ]; then
      run mkdir -p "$HOME/.local/share/slskd"
      # home.file used to own this path as a store symlink — replace it.
      [ -L "$HOME/.local/share/slskd/slskd.yml" ] && run rm "$HOME/.local/share/slskd/slskd.yml"
      run sh -c 'printf "web:\n  ip_address: 127.0.0.1,[::1]\n  https:\n    ip_address: 127.0.0.1,[::1]\n  authentication:\n    api_keys:\n      soul_sync:\n        key: \"%s\"\n        role: Administrator\n        cidr: 127.0.0.1/32,::1/128\n" "$(cat '"$keyFile"')" > "$HOME/.local/share/slskd/slskd.yml"'
      run chmod 600 "$HOME/.local/share/slskd/slskd.yml"
    fi
  '';
}
