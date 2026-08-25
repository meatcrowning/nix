{ pkgs, lib, ... }:

# Cross-machine sync for chatter's skills, tools and agent definitions.
#
# chatter (apps/oracle) reads its skills from ~/.local/share/oracle/skills, the
# tool manifests he and it write from ~/.local/share/oracle/tools, and its
# subagent definitions from ~/.local/share/oracle/agents — its OWN runtime
# dirs, deliberately not ~/.claude/skills, because that one belongs to Claude
# Code and the two sets drifted. Being runtime dirs they were machine-local, so
# a skill written on `top` never reached `book` and `book` in fact had neither
# directory at all. The stopgap was a manual one-way push
# (~/.local/share/oracle/seed-skills-to-book.sh, now redundant); this is the
# two-way version, on a timer, in both directions.
#
# Same engine as the other two: claude-memory-sync.sh, parametrized by CM_SYNC_*
# and already proven across these two machines for unrelated histories, push
# races and offline ticks. Only the environment differs.
#
# The REPO ROOT IS THE WHOLE RUNTIME DIR (~/.local/share/oracle), not skills/
# alone, because agents/ and tools/ have to come along and one repo cannot span
# three siblings. That dir also holds `sessions/`, `memory/`, `jobs/`, `sandbox/` and
# `images/` — every conversation he has had with chatter — so the seeded
# .gitignore is an ALLOWLIST: ignore everything at the root, re-include exactly
# skills/, agents/, tools/ and ctxfit.json — the last of those not because he
# writes it but because it is measured KV-cache bytes per token per MODEL, true
# on whichever machine reads it, and book (no local ollama) can never measure
# one for itself. A new store landing beside them cannot widen the push.
#
# Both machines get this: `home/` is shared verbatim between `top` and `air`
# via lam.nix + umport, and Fedora Asahi runs systemd the same as NixOS.

{
  xdg.configFile = {
    "scripts/oracle-skills-seed/gitignore".source = ./oracle-skills-files/gitignore;
    "scripts/oracle-skills-seed/gitattributes".source = ./oracle-skills-files/gitattributes;

    "scripts/oracle-skills-setup.sh" = {
      source = ./oracle-skills-files/oracle-skills-setup.sh;
      executable = true;
    };
  };

  systemd.user.services.oracle-skills-sync = {
    Unit.Description = "Sync chatter's skills, tools and agents with the private oracle-skills repo";
    Service = {
      Type = "oneshot";
      # Same PATH pinning rationale as the other two callers: the git credential
      # helper is `!gh auth git-credential`, so gh must be resolvable and the
      # ambient systemd-user PATH cannot be relied on for it.
      Environment = [
        "PATH=${lib.makeBinPath [
          pkgs.git
          pkgs.gh
          pkgs.coreutils
          pkgs.gnused
          pkgs.util-linux
          pkgs.inetutils
        ]}"
        "CM_SYNC_REPO=%h/.local/share/oracle"
        "CM_SYNC_REMOTE=https://github.com/meatcrowning/oracle-skills.git"
        "CM_SYNC_LOG=%h/.cache/oracle-skills-sync.log"
        "CM_SYNC_SEED=%h/.config/scripts/oracle-skills-seed"
        "CM_SYNC_LABEL=skill"
        # Belt-and-braces behind the allowlist. A skill may legitimately carry
        # reference guides and small scripts; nothing it carries should be tens
        # of megabytes, and the one thing that is — youtube-content's venv — is
        # already excluded by name. If this ever trips, look at what landed
        # before raising it.
        "CM_SYNC_MAX_MB=25"
      ];
      ExecStartPre = "%h/.config/scripts/oracle-skills-setup.sh";
      ExecStart = "%h/.config/scripts/claude-memory-sync.sh";
    };
  };

  systemd.user.timers.oracle-skills-sync = {
    Unit.Description = "Periodically sync chatter's skills, tools and agents across machines";
    Timer = {
      OnBootSec = "4min";
      # MUST accompany OnBootSec in a USER manager — OnBootSec counts from
      # SYSTEM boot and the user manager only starts at login, so a login more
      # than 4min after boot leaves the only elapse point already in the past
      # and the unit never fires at all. See the note in nix-docs.nix.
      OnStartupSec = "4min";
      OnUnitActiveSec = "5min";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };
}
