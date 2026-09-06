{ config, pkgs, lib, host, ... }:

{
  # Generate the config at activation so secrets never enter git or the Nix
  # store. Keep these untracked, one line, and mode 600:
  #
  #   printf '%s' 'your_soulseek_username' > ~/.secrets/slskd-username
  #   printf '%s' 'your_soulseek_password' > ~/.secrets/slskd-password
  #   chmod 600 ~/.secrets/slskd-username ~/.secrets/slskd-password
  #   sudo rebuild-top
  #   systemctl --user restart slskd
  #
  # Both web listeners and the Administrator key are loopback-only. Web login
  # is deliberately disabled for this single-user loopback UI; the retained API
  # key is compatibility for soulseek-missing.py.
  #
  # Only top advertises its local music library. Book's copy is an SMB view of
  # top, so re-serving it would duplicate traffic. Never use slskd's home-share
  # default. Download concurrency is explicitly 50 (the default is effectively
  # unlimited), and changes require a service restart.
  #
  # Load-bearing: slskd recursively watches its cwd independently of its share
  # list. A home-directory cwd exhausted top's 524288 inotify-watch budget.
  # Keep WorkingDirectory empty and pass --app-dir explicitly; changing HOME
  # does not prevent the walk.
  home.activation.slskdConfig = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    keyFile="$HOME/.secrets/slskd-api-key"
    if [ -f "$keyFile" ]; then
      run mkdir -p "$HOME/.local/share/slskd"
      # home.file used to own this path as a store symlink — replace it.
      [ -L "$HOME/.local/share/slskd/slskd.yml" ] && run rm "$HOME/.local/share/slskd/slskd.yml"
      # Share the music library on top (the files live on its SSD); an empty
      # list advertises nothing and reads as a leech to the network.
      host="${host}"
      sharesYml="  directories: []"
      if [ "$host" = "top" ]; then
        sharesYml=$'  directories:\n    - /run/media/lam/SSD/aud'
      fi
      run sh -c 'printf "web:\n  ip_address: 127.0.0.1,[::1]\n  https:\n    ip_address: 127.0.0.1,[::1]\n  authentication:\n    disabled: true\n    api_keys:\n      soul_sync:\n        key: \"%s\"\n        role: Administrator\n        cidr: 127.0.0.1/32,::1/128\ntransfers:\n  download:\n    slots: 50\nshares:\n%s\n" "$1" "$2" > "$3"' _ \
        "$(cat "$keyFile")" "$sharesYml" "$HOME/.local/share/slskd/slskd.yml"
      usrFile="$HOME/.secrets/slskd-username"
      pwdFile="$HOME/.secrets/slskd-password"
      if [ -f "$usrFile" ] && [ -f "$pwdFile" ]; then
        run sh -c 'printf "soulseek:\n  username: \"%s\"\n  password: \"%s\"\n" "$(cat '"$usrFile"')" "$(cat '"$pwdFile"')" >> "$HOME/.local/share/slskd/slskd.yml"'
      fi
      run chmod 600 "$HOME/.local/share/slskd/slskd.yml"
    fi
  '';

  # Run slskd as a systemd user service so the downloader has a live loopback
  # API. Deliberately NOT enabled since 2026-08-03: the download pipeline is
  # stopped at his request, so nothing auto-starts it. The unit file stays so a
  # later cleanup phase can start it for one-off downloads with
  # `systemctl --user start slskd`; to make it automatic again, re-add the
  # Install block below (or `systemctl --user enable slskd`). slskd watches its
  # config file by default and re-applies options on change; after adding the
  # two ~/.secrets files, a rebuild regenerates slskd.yml and a
  # `systemctl --user restart slskd` picks it up cleanly.
  systemd.user.services.slskd = {
    Unit = {
      Description = "slskd - Soulseek client for missing-track downloads";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      # --app-dir is what HOME would otherwise have decided; state is unmoved.
      ExecStart = "${pkgs.slskd}/bin/slskd --no-logo "
        + "--app-dir ${config.home.homeDirectory}/.local/share/slskd";
      # An empty cwd, so slskd's recursive watcher has nothing to walk. See the
      # measurement above; without this it eats the machine's whole inotify
      # budget. systemd creates the directory under $XDG_STATE_HOME.
      StateDirectory = "slskd-cwd";
      WorkingDirectory = "%S/slskd-cwd";
      Restart = "always";
      # always, not on-failure: when the Soulseek server connection drops,
      # slskd exits CLEANLY (code 0, NRestarts=0) so Restart=on-failure never
      # fires and the daemon stays down, silently taking the fill feeder with
      # it. Measured repeatedly 2026-08-09 (fill passes 2, 3, 4, 5 all died
      # this way). A clean-exit restart is idempotent and harmless here: slskd
      # re-enqueues its persisted download queue on startup and the feeder's
      # rescue/reconcile passes absorb the rest.
      RestartSec = 5;
    };
    # No Install.WantedBy: must not auto-start at login while the pipeline is
    # stopped. Manual start only (`systemctl --user start slskd`).
  };
}
