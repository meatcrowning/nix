# AGENTS.md — `~/nix`

This is a live, single-user desktop: there is no CI, test suite, or staging
box. A bad `sudo rebuild-top` costs the user's session. Be a critical peer,
measure screen-facing behavior with IPC/logs/traces, and finish changes:
edit → verify → focused commit → rebuild → push to `main`.

This file is the public root contract. `CLAUDE.md` is its symlink; edit this
file. The closest nested `AGENTS.md` wins for a file, and an explicit user
instruction wins over both. Read nested guides deliberately (not for free);
never add a nested `CLAUDE.md`.

## Start here — commands

Run these from `~/nix` on `top`; `rebuild-air` is the `book`/`air` wrapper:

```bash
cd ~/nix
./tools/preflight.sh
sudo rebuild-top                         # nixos-rebuild switch --flake /home/lam/nix#top
sudo rebuild-top --upgrade               # update inputs, then switch
nixos-rebuild build --flake /home/lam/nix#top
rebuild-air                              # home-manager switch --flake /home/lam/nix#air
```

Both wrappers run preflight and take `/tmp/claude-1000/-home-lam-nix/rebuild.lock`
with `flock -w 600`; `REBUILD_NO_PREFLIGHT=1` skips the wrapper's duplicate
preflight. Normal rebuilds use the repository's committed `HEAD`, not its
shared dirty working tree, so another agent's unfinished files cannot enter the
switch. Commit only your explicit paths first; `--upgrade` is the deliberate
exception because it must update `flake.lock`, and requires a clean ownership
check. `rbsys`, `rbhome`, and `update` are aliases from
`home/prog/zsh.nix`; home-manager is a NixOS module on `top`. The wrapper
hard-codes its flake and host, so bare `sudo nixos-rebuild ...` is not covered.
For other root commands use the askpass path and state the reason:

```bash
SUDO_ASKPASS_REASON="installing the new kernel module" sudo -A <cmd>
```

The wrapper falls back to ksshaskpass if the Qt dialog cannot start; see
`home/prog/askpass.nix` and `apps/askpass/AGENTS.md`.

Live-source workflow:

```bash
# Quickshell: rebuild, then force hot reload (the append is temporary)
sudo rebuild-top && printf '\n// x\n' >> ~/.config/quickshell/Theme.qml
# hyprland.lua: edit the Nix source, then reconcile and reload
sudo rebuild-top && hyprctl reload
# hyprvtb: bump main.cpp's version, then rebuild and reload
sudo rebuild-top && hyprctl reload
```

Never use `hyprctl plugin load` or `unload`. Apps under `apps/` run live
Python/QML source and need no rebuild unless their package/dependencies change.
Never run bare `qs`; it launches a second panel.

Read-only verification (never visual testing):

```bash
qs log | tail
qs ipc call view geom
qs ipc call view trace
qs ipc call state carried
qs ipc call launcher geom
qs ipc call wallpaper status
hyprctl plugin list
hyprctl configerrors
hyprctl layers
./tools/seed-drift.sh
./tools/seed-drift.sh --pre-switch
nix-pull
nix-pull apply
qmllint -I <import paths> qml/Main.qml
./tools/sandbox.sh start|exec CMD|shot|clients|stop
```

## Rebuild and reload policy

Rebuilding and reloading is standing behavior, at agent judgment, at any hour;
definition of done is applied, not merely pushed. Always run
`./tools/preflight.sh`, commit only the owned paths, then run the host command
(`sudo rebuild-top` on `top`, `rebuild-air` on `book`) with nothing staged
across it. The wrappers build that committed revision and exclude all remaining
working-tree WIP.
Report a rebuild/reload in one line.

Cheap Quickshell reloads and `hyprctl reload` are safe. Build `hyprvtb` and
reload it live when needed: since v2.65 the supervisor quarantines a failed
build (`sys/dsk/hyprland.nix` on `top`, the ly session entry on `book`). Never
run `hyprctl plugin load` or `unload`: it erases the plugin's config keys and
cannot be undone by `hyprctl reload`. If a rebuild bumps Hyprland or hyprutils, the
running compositor cannot load the new plugin; it becomes a next-login change.
Pins, login/logout behavior, and panel/plugin re-architecture remain ask-first.

## Testing without touching the user

Never touch the user's focus, pointer, clipboard, primary selection, windows,
workspace, notifications, OSDs, audio/MPRIS, gamma, brightness, cursor theme,
screen, or systemd user-manager environment. Do not launch a packaged app on
the real monitor, take screenshots, synthesize input, or script hyprvtb actions
(`rollup`, `minimize_active`, etc.). The user performs visual and interaction
checks; evidence is IPC, logs, and traces.

Use `tools/sandbox.sh` or `QT_QPA_PLATFORM=offscreen`. Source
`tools/lib/session-guard.sh` and use the matching guard immediately:
`sg_require_nested`, `sg_require_offscreen`, `sg_require_live_session`,
`sg_seat_snapshot`, `sg_seat_assert`, and (only for a compositor-side cursor
snap) `sg_pointer_pin CMD…`. A nested/offscreen failure must abort, never fall
through to inherited `WAYLAND_DISPLAY`/`HYPRLAND_INSTANCE_SIGNATURE` and the
user's session. Teardown belongs in a trap. Nested hyprvtb harnesses are the
exception: their positive per-run config-path check is stronger and they must
not source the shared guard.

`tools/sandbox.sh exec` verifies placement on the headless output and aborts
if a window lands elsewhere. `tools/leak-check.sh` runs from preflight and
warns (never blocks) on dead compositor env, stale locks, a second compositor,
a live sandbox, a test window on a real monitor, or a moved seat/pointer.
Repair with `~/.config/scripts/hypr-session-env.sh --restore` and
`tools/sandbox.sh stop`. The only intentional real-screen tool is
`tools/font-demo/font-demo.sh`; do not set `FONT_DEMO_ON_HIS_SCREEN=1`.

## Which machine

The start hook runs `~/.config/scripts/claude-host-id.sh` and supplies the host,
flake attribute, and rebuild command. Do not infer it from kernel details; if
the hook is absent, run `hostname`. The hosts are `top` (NixOS) and `book`
(Fedora Asahi, flake attribute `air`). Do not write `this machine`, `here`, or
similar host deixis into synced files; name `top` or `book`. Dispatch prompts
must name the host for rebuilds, `sys/`, compositor pins, or hardware work.

## Boundaries

Always:

- Apply changes to both `top` and `book` unless explicitly machine-specific;
  report a host exception by name.
- Edit Nix sources for mutable `~/.config/hypr/hyprland.lua` and
  `~/.config/quickshell/Theme.qml`; activation reconciles live copies. Run
  `tools/seed-drift.sh` afterward.
- Bump `main.cpp`'s version for every `hyprvtb` change.
- Update the nearest `AGENTS.md` when architecture changes.
- Keep new reference/spec/inventory docs under private `docs/`, never the public
  root. `AGENTS.md`, `README.md`, and `home/prog/hyprvtb/PORTING.md` are public
  exceptions. Do not add private machine facts to public files.
- Commit with an explicit pathspec through `tools/git-commit.sh`, push `main`,
  and remove a landed worktree (`git worktree remove ...`; `./tools/prune-worktrees.sh`).

Ask first:

- Bumping `hyprland` or `nixpkgs-quickshell` pins.
- Re-architecting the panel, plugin, or view gesture.
- Changing login/logout or causing windows to spawn at next login.
- Deleting/reorganizing anything under `~` outside this repo.
- Committing when ownership of existing tree changes is unclear.

Never:

- Run `git reset --hard`, `git checkout --`, `git restore`, `git stash`, or
  `git clean`; user edits are real and must survive.
- Commit without `-- <paths>` or use a pathless `git commit`/`-a`.
- Run `hyprctl plugin load`/`unload`.
- Let tests touch the live session or call `save_session()` from a script
  (manual Meta+Ctrl+S only).
- Edit live mutable copies, stage tracked files just to make Nix see them, or
  leave content staged across a rebuild/test/question.
- Bump a pin with unrelated changes, or hand-edit `/nix/store` symlinks such as
  `~/.zshrc`; edit sources under `home/`.

## Where things live

This is a routing map; feature history and incident transcripts belong in
private `docs/agents/` runbooks.

- `flake.nix` defines inputs, `top`, and `homeConfigurations.air`.
  `hosts/top/` and `sys/` are NixOS-only. `home/` is shared home-manager
  configuration; `lam.nix` imports it. `sys/` and `home/` use recursive
  `umport`; only `.nix` files are imported.
- `apps/` is inert vendored source outside those imports. Sources run from
  `/home/lam/nix/apps/<name>/main.py`, with packages in `home/prog/<name>.nix`;
  `apps/pylib/` moves with the tree. `apps/board/` is presented as `goetia`,
  while its stores are `docs/board.top.md` and `docs/board.book.md`; board text
  addresses `you`.
- `tools/` holds `preflight.sh`, `seed-drift.sh`, `seed-reconcile.sh`,
  `sandbox.sh`, `lib/session-guard.sh`, `leak-check.sh`, `heavy-gate.sh`,
  `boot-verify.sh`, and `prune-worktrees.sh`. Heavy remote rebuilds use
  `REBUILD_IGNORE_GPU=1`; `REBUILD_ASK_TIMEOUT` controls the gate. Use stub or
  headless harnesses (`heavy-gate-test.sh`, `seed-gate-test.sh`,
  `claude-merge-test.sh`, `board-merge-test.sh`, `boot-known-good-test.sh`,
  `ai-warden-test.py`, and the per-area tests); `heavy-gate.sh demo` is the
  real notification demo and `boot-verify.sh --vm` is opt-in.
- `home/srvs/hypr-env.nix` installs `hypr-session-env.sh`; use its `--check`
  detector and `--restore` repair path for manager/D-Bus compositor env.
  `sys/remote-power.nix` (top only) exposes `sudo -n remote-power status|reboot|reboot-force|reboot-sysrq`;
  `poweroff --confirm` is required. `known-good-boots list` inspects the
  top-only boot ring. Book-only Fedora seams are installed by commands in their
  file headers.
- `sounds/` is the private `vista-sounds` submodule. Clone with
  `--recurse-submodules` or run `git submodule update --init`; never commit its
  Microsoft `.wav` files here.
- `docs/` is a separate private repo (`github.com/meatcrowning/nix-docs`) inside
  this public checkout and ignored by its Git. `docs/` root is user-facing;
  `docs/agents/` is agent-only; `docs/README.md` indexes both. Its sync is
  `home/srvs/nix-docs.nix`; inspect `~/.cache/nix-docs-sync.log` or run
  `systemctl --user start nix-docs-sync.service`. A new sync caller must set
  `CM_SYNC_SEED`; do not use the `~/.claude` denylist for another tree.
- `~/.claude` and `~/.local/share/oracle/{skills,agents,tools}` are separate
  private runtime syncs. Edit their seeded source trees, not deployed copies;
  force them with `systemctl --user start claude-state-sync.service` and
  `systemctl --user start oracle-skills-sync.service`.
- `home/srvs/ai-warden.nix` arbitrates ollama/ComfyUI on `top`: admission
  control frees but never interrupts work, and fails open when unavailable.
  Check it with `systemctl --user is-active ai-warden` or `ai-warden status`.
  Board watchers/reminders/notifiers act only on the current host's board and
  have runbooks, logs, kill switches, and harnesses under `docs/agents/`.
  `nix-pull [check|apply]` is the only pull/apply path; it uses `--ff-only` and
  never stashes, resets, or checks out.

## Design and nested guides

Read private `docs/DESIGN.md` before any visual change. It governs typography,
palette, spacing, corners, motion, titlebar buttons, menus, rows, drag feedback,
and the rule never to offer an action that can silently fail. Read
`docs/agents/his-voice.md` Part A before writing any desktop-visible string;
Part B governs replies: a landed change is one line saying what it does and
the pushed `<sha>`, unless there is a problem. Read `docs/HARDWARE.md` before
measuring hardware.

| Editing | Read next |
|---|---|
| Anything visual | `docs/DESIGN.md`, then the relevant row |
| Desktop-visible strings | `docs/agents/his-voice.md` Part A |
| Hardware or host choice | `docs/HARDWARE.md` |
| Quickshell panel | `home/prog/quickshell-files/AGENTS.md` |
| Hyprland, hyprvtb, sandbox | `home/prog/AGENTS.md` |
| Compositor pin/plugin ABI | `home/prog/hyprvtb/PORTING.md` |
| Qt app | `apps/AGENTS.md`, then `apps/<name>/AGENTS.md` |

Leave `PORTING.md` in the plugin source. Repathing its six bare `DESIGN.md`
comments changes the derivation and requires the next `hyprvtb` version bump;
fold that into a substantive plugin change.

## Conventions

`flake.nix` passes `host = "top" | "air"` to every `home` module. Use
`{ host, ... }:` or a platform predicate rather than a new per-host file;
`hosts/air/` does not exist. Gate x86-only packages with
`lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [...]` and inspect the other
host branch whenever touching a conditional. `home/` is evaluated by both
hosts, so accidental top-only paths can silently do nothing on `book`.

`nixpkgs` follows `nixos-unstable`; exact pins protect `hyprland` and
`nixpkgs-quickshell`. `hyprland-air` is a temporary v0.56.2 pin for Fedora
Asahi; ask before changing any pin. `my.aerotheme.enable` is a `top` greeter
choice; `defaultSession` remains `hyprland`.

Tailscale is allowlisted per interface: `top` exposes only 22/445 on
`tailscale0`, and loopback services (ComfyUI 127.0.0.1:8188) remain loopback,
using `apps/painter/tools/comfy-tunnel.sh`. On `book`, Fedora setup is
`dnf install tailscale`, `systemctl enable --now tailscaled`,
`sudo tailscale set --operator=lam`, then `tailscale up`; joining requires a
human opening the URL. The library mount is `//top/aud`, not `.local`.

## Git and landing

Check ownership first:

```bash
git -C ~/nix status
```

Tracked working-tree edits need no staging for flake evaluation. New files use
`git add -N path`; never stage tracked content just for a rebuild. The index is
shared. `tools/preflight.sh` warns about staged content and untracked Nix/QML/
Lua/shell files. `tools/git-commit.sh` prints the exact diff, refuses suspicious
large mixed-WIP files, supports `--yes-file`, and supports ownership-safe
`--hunks`:

```bash
tools/git-commit.sh -m "subject" -- path/one path/two
tools/git-commit.sh -m "subject" --hunks -- path
git commit -m "subject" -- path/one path/two  # only when every hunk is yours
git add -N path/new-file.qml                 # intent-to-add; no content staged
git push origin main
```

A pathspec alone still takes the whole working-tree copy of that file, so use
the helper and confirm every hunk. Commit subjects are imperative, lowercase,
≤72 characters, with a body only for a short non-obvious why; end with the
`Co-Authored-By` trailer. Then push `main`. This explicit flow overrides a
background harness's no-push/PR defaults. After a landed worktree:

```bash
git worktree remove <path> && git branch -D <wt-branch>
./tools/prune-worktrees.sh
```

## Maintaining this guide

Keep substantial architecture, top-level directories, and major options
represented here or in the closest nested guide. Keep root detail to commands,
boundaries, routing, and cross-cutting rules; move area-specific history to
`docs/agents/`. Lead with the rule and preserve the sharp consequence, not the
incident transcript that originally motivated it. Keep system changes in
`sys/`, user changes in `home/`, and prefer a focused imported `.nix` module to
bloating `configuration.nix` or `lam.nix`.
