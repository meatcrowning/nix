{ config, pkgs, lib, host, ... }:

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
  # Web authentication is DISABLED (`authentication.disabled: true`) on
  # purpose: the UI is loopback-only and belongs to one user, so there is
  # nothing to keep out and a login wall is pure friction. slskd's web auth is
  # ON by default (user/pass `slskd`/`slskd`) unless `disabled` is set, and
  # that default was the 401 wall he hit — the config never turned it off, and
  # a JWT-only session lapses the moment the service restarts (random JWT
  # secret each start). Disabled routes every endpoint through passthrough
  # auth (Anonymous/Administrator), so the API key below is now a no-op —
  # kept only because soulseek-missing.py still sends it and the check is
  # bypassed either way.
  #
  # `shares.directories` points the music library at `top` and stays empty on
  # `book`. An empty share list is the honest config for a downloader that
  # serves nothing, but it also means NO files are advertised — no browse, no
  # search hits — so the network reads him as a leech and he hits share-ratio /
  # leech download refusals. Sharing fixes that: there is no separate "browse"
  # flag in slskd, a non-empty `directories` list is what makes files browsable
  # and searchable by peers.
  #
  # Keep the share dirs real and explicit — never slskd's own default of sharing
  # `~/` (the whole home dir), which is both something this repo must not leak
  # and a full-tree scan that leaves the service stuck in D-state on an old Nix
  # install under $HOME (measured: read 2.8GB and never fully started).
  #
  # `top` shares `/run/media/lam/SSD/aud`, the same 208GB tree the player scans
  # (546 dirs ≈ a few hundred inotify watches — no risk to the watch budget, and
  # slskd's recursive CWD watcher is already quarantined to the empty
  # `WorkingDirectory` below). `book` deliberately keeps `[]`: the library
  # physically lives on `top`'s SSD and `book` sees it only as an SMB mount back
  # to `top`, so serving the same files from `book` over the LAN to the internet
  # would double the read load on `top`'s samba for identical content. Gated on
  # `host`, not on path, so both machines evaluate the same file.
  #
  # `global.download.slots` caps how many downloads proceed at once. Do not be
  # misled by the `global:` key — 0.24.x reads that (master later renamed the
  # block `transfers:`); it feeds the Soulseek client's
  # `maximumConcurrentDownloads`, i.e. the number of simultaneous download
  # connections slskd will hold. It is read once at startup (OptionsAtStartup in
  # Program.cs), so changing it needs a `systemctl --user restart slskd`, not
  # just the yml regen that this rebuild performs.
  #
  # Left unset, slskd defaults it to int.MaxValue — effectively UNLIMITED
  # (measured: the live API reported 2147483647 before this was pinned). For a
  # batch downloader that is the risky configuration, not the safe one: it opens
  # one download connection per queued file at once, so a large missing-track
  # batch fans out indiscriminately and hammers whichever peer happens to hold
  # many of the requested files.
  #
  # Pinned to 50. That is enough concurrent in-flight downloads to drain a long
  # queue across many distinct peers, and it is safe to queue that aggressively:
  # Soulseek does NOT rate-limit or penalize a user for queuing many downloads.
  # The only real constraint is per-uploader upload slots — each peer grants just
  # a few simultaneous uploads, so anything queued beyond those slots simply
  # waits in that peer's queue rather than throttling or banning you. 50 bounds
  # the fan-out so a single peer (or this box's own connection budget) is never
  # deluged.
  #
  # THAT IS NOT ENOUGH ON ITS OWN, because the empty share list stops the SCAN
  # and not the WATCHER. slskd registers a recursive inotify watch rooted at its
  # **current working directory**, whatever that is and whatever it shares —
  # measured on `top` 2026-08-01: the service reported "Sharing 0 directories
  # and 0 files" while holding **524,006 of the box's 524,288 inotify watches**,
  # the first one on `/home/lam` itself (a user unit's default cwd) and 322k of
  # them inside `~/drives/nixos-old`, an old NixOS install's /nix/store with
  # 355k directories. It reaches that ceiling ~15s after start and stays there,
  # so every other inotify user on this uid is starved: `board-inbox.path` could
  # not arm ("Failed to add a watch ... inotify watch limit reached") and
  # anything typed into goetia went nowhere for 8.5 hours.
  #
  # So the fix is a `WorkingDirectory` with nothing under it. It is cwd and NOT
  # `$HOME` — that was measured too, because the obvious guess is wrong and cost
  # a rebuild to disprove: empty cwd + real HOME gives **25** watches, while
  # `cwd=/home/lam` + an empty HOME still gives **524,025**. `--app-dir` is
  # named explicitly so none of slskd's own paths depend on either.
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
      run sh -c 'printf "web:\n  ip_address: 127.0.0.1,[::1]\n  https:\n    ip_address: 127.0.0.1,[::1]\n  authentication:\n    disabled: true\n    api_keys:\n      soul_sync:\n        key: \"%s\"\n        role: Administrator\n        cidr: 127.0.0.1/32,::1/128\nglobal:\n  download:\n    slots: 50\nshares:\n%s\n" "$1" "$2" > "$3"' _ \
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
