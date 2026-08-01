{ config, pkgs, lib, ... }:

{
  # slskd's web API key lives OUTSIDE this repo in ~/.secrets/slskd-api-key
  # (mode 600, untracked) so it never enters git history. The yml is
  # therefore generated at activation time from that file, instead of being
  # a home.file symlink with the key baked into the nix store.
  #
  # slskd's Soulseek login is handled the same way, by the same rule (a
  # secret this repo must not hold): ~/.secrets/slskd-username and
  # ~/.secrets/slskd-password, each one line, mode 600, untracked. When both
  # exist, the activation appends a `soulseek:` block to the yml, so slskd
  # logs in and searches stop 409-ing. Until then the config is still valid
  # (web-only) and the downloader's "not logged in" message is honest. Add
  # both files, then rebuild (regenerates slskd.yml) and restart the service:
  #
  #   printf '%s' 'your_soulseek_username' > ~/.secrets/slskd-username
  #   printf '%s' 'your_soulseek_password' > ~/.secrets/slskd-password
  #   chmod 600 ~/.secrets/slskd-username ~/.secrets/slskd-password
  #   sudo rebuild-top
  #   systemctl --user restart slskd
  #
  # slskd's web UI defaults to `web.ip_address: 0.0.0.0,[::]` (all interfaces)
  # — the firewall doesn't open its port, but that still leaves it reachable to
  # any other local process/user and to SSRF from a browser. Pin both the HTTP
  # and HTTPS listeners to loopback, and scope the Administrator key's CIDR to
  # loopback too, so it can't be presented from anywhere but this box.
  # (Key names/structure per slskd's slskd.example.yml `web:` block.)
  #
  # `shares.directories` is pinned to empty on purpose. slskd's default is to
  # share `~/`, the whole home directory — which is both something this repo
  # must not leak and a full-tree scan that leaves the service stuck in D-state
  # on an old Nix install under $HOME (measured: read 2.8GB and never fully
  # started). This downloader only pulls missing tracks; it serves nothing, so
  # an empty share list is the honest config. Add real share dirs here if that
  # ever changes.
  home.activation.slskdConfig = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    keyFile="$HOME/.secrets/slskd-api-key"
    if [ -f "$keyFile" ]; then
      run mkdir -p "$HOME/.local/share/slskd"
      # home.file used to own this path as a store symlink — replace it.
      [ -L "$HOME/.local/share/slskd/slskd.yml" ] && run rm "$HOME/.local/share/slskd/slskd.yml"
      run sh -c 'printf "web:\n  ip_address: 127.0.0.1,[::1]\n  https:\n    ip_address: 127.0.0.1,[::1]\n  authentication:\n    api_keys:\n      soul_sync:\n        key: \"%s\"\n        role: Administrator\n        cidr: 127.0.0.1/32,::1/128\nshares:\n  directories: []\n" "$(cat '"$keyFile"')" > "$HOME/.local/share/slskd/slskd.yml"'
      usrFile="$HOME/.secrets/slskd-username"
      pwdFile="$HOME/.secrets/slskd-password"
      if [ -f "$usrFile" ] && [ -f "$pwdFile" ]; then
        run sh -c 'printf "soulseek:\n  username: \"%s\"\n  password: \"%s\"\n" "$(cat '"$usrFile"')" "$(cat '"$pwdFile"')" >> "$HOME/.local/share/slskd/slskd.yml"'
      fi
      run chmod 600 "$HOME/.local/share/slskd/slskd.yml"
    fi
  '';

  # Run slskd as a systemd user service so the downloader always has a live
  # loopback API without the user starting it by hand. slskd watches its config
  # file by default and re-applies options on change; after adding the two
  # ~/.secrets files, a rebuild regenerates slskd.yml and a
  # `systemctl --user restart slskd` picks it up cleanly.
  systemd.user.services.slskd = {
    Unit = {
      Description = "slskd - Soulseek client for missing-track downloads";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      ExecStart = "${pkgs.slskd}/bin/slskd --no-logo";
      Restart = "on-failure";
      RestartSec = 5;
    };
    Install.WantedBy = [ "default.target" ];
  };
}
