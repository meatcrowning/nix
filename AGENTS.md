# AGENTS.md — ~/nix

This is a live desktop with no CI or staging host. Use IPC, logs, and isolated
harnesses for verification. Finish changes: edit → verify → focused commit →
host rebuild → push to main. Keep replies concise; report the result and commit,
plus any problem the user needs to know about.

This guide applies to every agent. CLAUDE.md is its symlink; edit this file.
Read the relevant nested guide before editing; the closest guide wins, and
explicit user instructions take precedence. Do not add nested CLAUDE.md files.

## Host and commands

Use the measured host/session from ~/.config/scripts/claude-host-id.sh; if
absent, run hostname. top is NixOS; book is Fedora Asahi, flake host air.
Do not infer the active compositor from defaults or the host from the kernel.
Name hosts explicitly in synced notes and hardware/rebuild dispatches.

Run from /home/lam/nix:

~~~bash
git status --short
./tools/preflight.sh
tools/git-commit.sh -m "subject" -m "Co-Authored-By: Name <email>" -- path/one path/two
sudo rebuild-top                  # top: NixOS including home-manager
rebuild-air                        # book: home-manager
git push origin main
~~~

Rebuilds/reloads are authorized at agent judgment, at any hour. Both wrappers
run preflight and build committed HEAD, excluding dirty WIP. Commit owned paths
first and leave nothing staged across a rebuild, test, or question. Both lock
/tmp/claude-1000/-home-lam-nix/rebuild.lock (flock -w 600);
REBUILD_NO_PREFLIGHT=1 skips their duplicate preflight.
sudo rebuild-top --upgrade updates inputs and requires a clean ownership
check. Other root commands use SUDO_ASKPASS_REASON="reason" sudo -A <cmd>;
askpass falls back to ksshaskpass. See apps/askpass/AGENTS.md.
Heavy remote rebuilds use REBUILD_IGNORE_GPU=1; REBUILD_ASK_TIMEOUT controls
the gate.

Use tools/nix-private.sh eval|build for manual flake evaluation/builds:

~~~bash
./tools/nix-private.sh build .#nixosConfigurations.top.config.system.build.toplevel
~~~

The private input is docs/private-config/. Restore it on both hosts before
applying updates; its public fallback refuses evaluation. Wrappers override it
locally with --no-write-lock-file. Use plain nix flake update for input
updates. Never put personal values or the resolved private input into public
source, lock files, or commit messages. Credentials stay encrypted/runtime-only;
other private settings still enter the local store. Preflight's privacy check
also verifies the public noreply Git identity (home/git-privacy.nix).

## Applying changes

- Support both hosts unless the request is machine-specific; inspect both sides
  of host conditionals and report exceptions by name.
- Edit sources for ~/.config/hypr/hyprland.lua and
  ~/.config/quickshell/Theme.qml. Activation reconciles the live files;
  run tools/seed-drift.sh afterward.
- After a Hyprland config/plugin rebuild, run hyprctl reload. Bump
  hyprvtb/main.cpp's version for every plugin change. Never use
  hyprctl plugin load or unload: unloading erases config keys that reload
  cannot restore. A Hyprland/hyprutils ABI change takes effect next login.
- Quickshell needs a forced hot reload after symlink changes; use its nested
  guide. Never run bare qs, which starts a second panel.
- Apps run live Python/QML source and need no rebuild unless packaging or
  dependencies change. Do not relaunch the user's apps for verification.
- nix-pull [check|apply] is the only pull/apply path; it uses --ff-only.

Ask before changing compositor/Quickshell pins (including hyprland-air),
panel/plugin/view-gesture architecture, login/logout behavior, or next-login
app launches. Also ask before deleting/reorganizing anything outside this repo,
force-pushing history, or committing edits whose ownership is unclear.

## Test isolation

Never let tests touch the user's focus, pointer, clipboard/primary selection,
windows/workspaces, notifications/OSDs, audio/MPRIS, gamma, brightness, cursor
theme, screen, or systemd user-manager environment. Do not launch test apps on
the real monitor, take live screenshots, synthesize input, script hyprvtb window
actions, or call save_session() (manual Meta+Ctrl+S only).
The user performs visual/interaction checks. If IPC/logs/traces cannot resolve
a visual bug, request permission for the specific live test and turn.

Use tools/sandbox.sh start|exec CMD|shot|clients|stop or
QT_QPA_PLATFORM=offscreen. Source tools/lib/session-guard.sh and immediately
use the matching guard: sg_require_nested, sg_require_offscreen,
sg_require_live_session, sg_seat_snapshot, sg_seat_assert; use
sg_pointer_pin CMD… only for a compositor-side cursor snap.
Abort on isolation failure; never fall through to inherited display/compositor
environment. Put teardown in a trap. Nested hyprvtb harnesses instead require
their own positive per-run config-path check and must not source this guard.

Sandbox exec verifies headless placement. Preflight's tools/leak-check.sh
warns about leaked sessions, stale locks/environment, test windows, and moved
seat/pointer. Repair with ~/.config/scripts/hypr-session-env.sh --restore and
tools/sandbox.sh stop. Never enable FONT_DEMO_ON_HIS_SCREEN=1 or run
heavy-gate.sh demo as a test; boot-verify.sh --vm is opt-in.

Read-only checks include qs log, qs ipc call view geom, qs ipc call view trace,
qs ipc call state carried, qs ipc call launcher geom,
qs ipc call wallpaper status, hyprctl plugin list, hyprctl configerrors,
and hyprctl layers. Use the per-area harnesses and qmllint with correct
import paths. seed-drift.sh --pre-switch reports expected reconciliation.

## Layout and references

| Area | Source / guide |
|---|---|
| Visual changes | Private docs/DESIGN.md; match existing session conventions for UI text |
| Hardware measurements | Private docs/HARDWARE.md |
| Qt apps | apps/AGENTS.md, then apps/<name>/AGENTS.md |
| Quickshell | home/prog/quickshell-files/AGENTS.md |
| Hyprland, hyprvtb, sandbox | home/prog/AGENTS.md |
| Plugin ABI/pins | home/prog/hyprvtb/PORTING.md |

- flake.nix defines top and homeConfigurations.air. hosts/top/ and sys/ are
  NixOS-only; lam.nix imports shared home/. Recursive umport imports only .nix
  files. Keep system changes in sys/, user changes in home/, and use focused
  modules. There is no hosts/air/.
- Home modules receive host = "top" | "air". Use that or platform predicates;
  gate x86-only packages with lib.optionals pkgs.stdenv.hostPlatform.isx86_64.
- apps/ is vendored source outside Nix imports; wrappers in
  home/prog/<name>.nix run /home/lam/nix/apps/<name>/main.py.
  Keep apps/pylib/ with the tree. apps/board/ is goetia; its host-local
  boards are docs/board.top.md and docs/board.book.md, addressed to “you”.
- Shared Plasma visuals live in home/plasma.nix and Oxygen/colour modules
  under home/prog/. Capture durable visual settings there, without output IDs.
  Wallpaper selection/library is host-local; Style owns it after one-time
  bootstrap. Never sync Plasma containments or ~/Pictures/Wallpapers.
- Labwc is top-only (sys/dsk/labwc.nix, home/prog/labwc.nix).
  Its config is seeded once and owned by its tools; never reconcile it.
  Hyprland remains the default greeter session.
- Book's custom Hyprvtb, Konsole, and Nix Qt6 Oxygen use lib/air-offload.nix
  and top's restricted builder (sys/book-builder.nix).
  See tools/book-builder-setup.sh; cap local ARM jobs in rebuild-air.
  Fedora Oxygen remains a native build.
- home/srvs/hypr-env.nix owns compositor environment repair.
  sys/remote-power.nix and known-good-boots are top-only; poweroff requires
  --confirm. Book-only Fedora setup commands are in the relevant file headers.
- home/srvs/ai-warden.nix arbitrates ollama/ComfyUI on top: never interrupt
  work, fail open when unavailable. Check with ai-warden status.
  Board watcher runbooks, logs, kill switches, and harnesses are in docs/agents/.
- Keep loopback services loopback-only; ComfyUI uses
  apps/painter/tools/comfy-tunnel.sh. Top's tailscale0 allows only 22/445.
  Book's Tailscale login requires a human opening its URL; the library share is
  //top/aud, not .local.
- sounds/ is the private vista-sounds submodule. Use
  git submodule update --init; never add its Microsoft WAV files to this repo.
- docs/ is a separate private Git repo: human references at its root, agent
  runbooks in docs/agents/, index in docs/README.md. Its timer is
  home/srvs/nix-docs.nix; inspect ~/.cache/nix-docs-sync.log or start
  nix-docs-sync.service. New sync callers must set CM_SYNC_SEED.
- ~/.claude and ~/.local/share/oracle/{skills,agents,tools} have separate
  private syncs. Edit seeded sources, not deployed copies; their services are
  claude-state-sync.service and oracle-skills-sync.service. Do not reuse the
  ~/.claude denylist for other trees.

## Git and documentation

Preserve unrelated working-tree edits. Never use git reset --hard,
git checkout --, git restore, git stash, or git clean; never hand-edit
Nix-store symlinks. Tracked edits need no staging for evaluation; new files use
git add -N path.

Commit through tools/git-commit.sh with explicit -- <paths>. A pathspec takes
the whole file: review every hunk; use --hunks for mixed ownership or --yes-file
PATH for a reviewed large edit. Never use pathless commits or -a. Subjects are
imperative, lowercase, ≤72 characters; include a Co-Authored-By trailer.
Push main. Remove landed worktrees and their branches, then run
tools/prune-worktrees.sh.

Keep guides to commands, ownership, architecture, and non-obvious constraints.
Document a fact once, near its owner; comments explain reasons the code cannot.
Do not append incident transcripts, user quotes, completion reports, or
before/after essays. Git preserves change history. Update guides when their
contracts change, not for every fix. New reference/spec/inventory documents
belong in private docs/; public exceptions are AGENTS.md, README.md, and
hyprvtb/PORTING.md. Do not move/repath plugin documentation for tidiness:
changes inside its source directory alter the derivation and require a version
bump; combine those with substantive plugin work.
