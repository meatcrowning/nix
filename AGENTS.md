# AGENTS.md — `~/nix`

The NixOS flake that builds this machine. **It is a live, single-user desktop:
there is no CI, no test suite and no staging box.** `sudo rebuild-top` switches
the machine the user is sitting at, and a bad change costs them their session,
not a red build. Work like a colleague who has to sit at this desk afterwards.

**How to work here**

- **Be a critical peer, not an order-taker.** If a request would regress
  something these files call load-bearing, say so in a sentence — then do the
  work.
- **Finish the job.** Edit → verify → rebuild → commit → push to `main`. Those
  steps are pre-authorized (see Boundaries); don't stop to ask for them.
- **Measure, don't reason, about anything on screen.** The user does all
  visual checks. Your evidence is IPC, logs and traces — and your test never
  touches his session; see "Testing without interfering with the user".
- **These files are the source of truth for agent instructions here.**
  `CLAUDE.md` at this root is a symlink to this one — edit the `AGENTS.md`.
  Per-area detail lives in nested `AGENTS.md` files — **the closest one to the
  file you are editing wins**, and an explicit instruction from the user
  overrides all of them. **Those nested guides are yours to OPEN, not
  free**: the nested `CLAUDE.md` symlinks were deleted on 2026-07-30 because
  each one injected its whole guide into any agent that touched a file
  underneath it, on every turn — measured, reading a 3.6 KB `Theme.qml` cost
  **45.8k tokens** against 27.7k for the same read outside those trees, the
  difference being `home/prog` + `quickshell-files` swallowed entire. So read
  the nearest guide deliberately and in slices (see rule 6 in
  `boardwork.RULES`, and "Nested guides" below), and **never re-add a nested
  `CLAUDE.md`**.

---

## Start here — the commands

Rebuild. Passwordless via a NOPASSWD rule on the wrapper only, so it works with
no tty: **just run it, don't ask, don't hand it back to the user.**

```bash
cd ~/nix
./tools/preflight.sh        # THE pre-rebuild gate: untracked .nix/.qml/.lua/.sh, staged-index
                            # warning, rootless eval, seed drift, stale compositor
                            # env in the systemd user manager (~10s)
sudo rebuild-top            # = nixos-rebuild switch --flake /home/lam/nix#top   (aliases: rbsys/rbhome)
sudo rebuild-top --upgrade  # = `update`; bumps flake inputs first
nixos-rebuild build --flake /home/lam/nix#top   # optional, no sudo at all, warms the store
rebuild-air                 # book's wrapper for `home-manager switch --flake /home/lam/nix#air`
```

**Both wrappers run preflight and take the shared rebuild lock themselves**
(`/tmp/claude-1000/-home-lam-nix/rebuild.lock`, `flock -w 600`), so a rebuild
via `sudo rebuild-top` on `top` or `rebuild-air` on `book` needs no manual
`flock` and cannot race a concurrent agent's rebuild. Running preflight by
hand first is still fine — and still what you do before non-wrapper work
(`nixos-rebuild build`, a bare `home-manager switch`). `REBUILD_NO_PREFLIGHT=1`
skips the built-in preflight; a failing preflight aborts the switch.

`rbsys`, `rbhome` and `update` are all the same command here (`home/prog/zsh.nix`)
— home-manager is a NixOS module on `top`, so there is no standalone
`home-manager switch` and `rbhome` is **not** a separate or dangerous command.
`rebuild-top` is a `writeShellScriptBin` wrapper that hardcodes the flake and
host, so the NOPASSWD rule (`sys/nixos-rebuild.nix`) cannot be abused into
arbitrary root — which is why bare `sudo nixos-rebuild switch …` is **not**
covered and will hang on the missing tty. Use the wrapper. For any *other* root command use
`sudo -A <cmd>`: `SUDO_ASKPASS` is wired to our own dialog
(`home/prog/askpass.nix` → `apps/askpass`), so it prompts the user instead of
failing. Plain `sudo <cmd>` just fails in an agent shell. The wrapper falls back
to ksshaskpass if that dialog cannot start (exit 3), so `sudo -A` cannot be
taken out by a Qt/PySide6 breakage — see `apps/askpass/AGENTS.md`.

**Say why you need root.** The dialog shows a reason, supplied by the caller and
never invented by the dialog; set it on every `sudo -A` you run:

```bash
SUDO_ASKPASS_REASON="installing the new kernel module" sudo -A <cmd>
```

The *command* is shown regardless — the dialog reads it from the waiting sudo's
own argv via `/proc`, because in practice nobody ever set the variable and the
prompt therefore only ever said `NO REASON GIVEN`. The reason still adds the one
thing argv cannot say: **why**.

Get an edit live:

```bash
# panel (.qml)     — rebuild, then force Quickshell's hot reload; see home/prog/quickshell-files/AGENTS.md
sudo rebuild-top && printf '\n// x\n' >> ~/.config/quickshell/Theme.qml   # then restore the file

# hyprland.lua     — edit the nix SOURCE only; the switch reconciles the live copy:
sudo rebuild-top && hyprctl reload

# hyprvtb (C++)    — bump the version in main.cpp, then:
sudo rebuild-top && hyprctl reload    # NEVER `hyprctl plugin load/unload`

# apps/ (.py/.qml) — live source, no rebuild. No hot reload either: relaunch the app.
```

Verify without looking at the screen:

```bash
qs log | tail                     # panel parse/binding errors — CUMULATIVE, snapshot the line count first
qs ipc call view geom             # panel widths + drag thresholds
qs ipc call view trace            # per-pointer-event samples of the last drag
qs ipc call state carried         # what survived the last panel reload
qs ipc call launcher geom         # is the CLOSED runner drawer exactly the notch?
qs ipc call wallpaper status      # path, mode, and whether the frame actually decoded
hyprctl plugin list               # exactly one hyprvtb, at the new Version
hyprctl configerrors              # must be empty
hyprctl layers                    # layer namespaces + sizes
./tools/seed-drift.sh             # AFTER a switch: did the reconciler miss a value? exit 1 = it did
./tools/seed-drift.sh --pre-switch # BEFORE one: what this switch will do to the two mutable dotfiles
nix-pull                          # what origin/main has that this checkout does not, and what applying costs
nix-pull apply                    # pull --ff-only, rebuild through this host's wrapper, reload
qmllint -I <import paths> qml/Main.qml
./tools/sandbox.sh start|exec CMD|shot|clients|stop    # off-screen monitor for GUI tests
```

Never run bare `qs` — it launches a second panel.

---

## When it is okay to rebuild or hot-reload

**This is THE rule, and it binds every agent here — interactive, background, or
spawned by the board.** It was scattered across a memory, a boundary and three
prompts until 2026-07-29; it lives here now so nobody has to have read the right
memory to know it.

**Rebuilding and reloading is standing behaviour, at your judgement, at any
hour.** Don't queue it for when he is away, don't ask, don't hand it back as
*"to go live, run…"*. Definition of done for a change here is *applied*, not
*pushed*. He is at the machine most of the time and said so explicitly: any
time, on the agent's judgement.

What that judgement is made of — the parts that are **not** free:

- **Preflight, then the host's own command.** `./tools/preflight.sh`, then
  `sudo rebuild-top` on `top` / `home-manager switch --flake ~/nix#air` on
  `book`. Nothing staged in the index across it (see The index is SHARED).
- **Cheap reloads are cheap, so just do them.** The Quickshell `Theme.qml`
  bump and `hyprctl reload` cannot take the session with them — a QML parse
  error keeps the old tree and toasts, and `reload` re-runs the live Lua with
  no session disturbance.
- **The compiled `hyprvtb` hot-swap is the one that is not.** Build it always;
  `hyprctl reload` swaps it live and is survivable *by design* since v2.65,
  with `hypr-supervise` quarantining a build that dies — on `top` through the
  NixOS session wrapper (`sys/dsk/hyprland.nix`), on `book` through ly's
  session entry since 2026-08-03 (`docs/agents/book-supervised-session.md`).
  book's live `hyprland.lua` has carried the resolved-path + quarantine load
  block since 2026-07-26 and swaps fine on `hyprctl reload`; the crash net now
  covers both machines, so a bad build costs the previous plugin version and a
  `quarantined` breadcrumb, not a relog. So swap it live on either machine if
  the work needs it. **Never `hyprctl plugin load` / `unload`** on either —
  that one is unconditional and unrecoverable.
- **A rebuild that bumps Hyprland or hyprutils makes any live swap impossible**
  (the new plugin links a newer toolchain than the running compositor). Then it
  is next-login, and saying so is part of the job.
- **The Ask-first list below is unchanged.** Pin bumps, anything that changes
  login/logout, re-architecting the panel or the plugin: those are still his
  call, and this rule does not reach them.
- **Say what you did.** A rebuild or a reload is reported, in a line — not
  narrated, not silent.

The only agents this does not apply to are ones told otherwise in their own
prompt for a specific run: an explicit instruction from him always wins.

---

## Testing without interfering with the user

**Never let a test touch anything he can see, hear, type into or click on.** He
is sitting at this desk while you work — on 2026-07-30 workers took his keyboard
focus out from under him mid-sentence, and his correction was *"not just
keyboard, mouse... everything! its like they forgot how to properly do testing
outside the desktop without interfering with the user"*. A test that reaches the
live session is a bug in the test, not the price of testing.

His, and not yours to borrow even for a second:

- **Keyboard and pointer focus** — no focusing a window, no warping the cursor,
  no synthetic clicks or key events. **And grepping for a cursor dispatcher is
  not how you check that**: the compositor moves his pointer on its own, for
  things that do not look like pointer calls at all. Removing an output
  (`hyprctl output remove`, i.e. every `tools/sandbox.sh stop`) snaps the cursor
  to the exact centre of the surviving monitor, and `hl.dsp.focus({monitor=…})`
  warps it to the focused window's middle — **neither obeys `cursor:no_warps`**.
  That was "the mouse still gets stolen / randomly moved to the center of the
  screen", it survived an audit that grepped for `movecursor`, and the fix is
  `sg_pointer_pin` (below), which puts the pointer back where it read it.
- **The clipboard and the primary selection.**
- **His active window and workspace.** In particular, never script hyprvtb's Lua
  actions (`rollup`, `minimize_active`, …) to probe behaviour: `hl.dsp.focuswindow`
  is nil, so they land on HIS window.
- **Any window on the real monitor** — `tools/sandbox.sh` or
  `QT_QPA_PLATFORM=offscreen`, never a packaged app "just to check", never bare
  `qs` (it launches a second panel).
- **Notifications and OSDs.**
- **Audio playback and MPRIS** — never drive the running player; he listens on it
  live. A muted headless harness, or nothing.
- **Gamma/brightness and the cursor theme** — global, and both outlive the
  process that set them.
- **The systemd user manager environment.** Every Hyprland, nested test ones
  included, overwrites `HYPRLAND_INSTANCE_SIGNATURE`/`WAYLAND_DISPLAY` in that
  manager-global store, and one killed with `SIGKILL` never gives it back — see
  `home/srvs/hypr-env.nix` under Where things live. Any harness that starts a
  compositor calls `hypr-session-env.sh --restore` on teardown.
- **Screenshots and driving the GUI** — he does every visual, animation and
  interaction check himself. Your evidence is IPC, logs and traces.

**Tear down in a trap, not at the end of the happy path.** The leaks that reach
him come from tests that failed halfway.

**Never fall back to his session. Abort instead.** The way a careful harness
still reaches him is the SILENT DEGRADE: it means to drive a nested compositor
or an offscreen client, that target does not come up, `WAYLAND_DISPLAY` /
`HYPRLAND_INSTANCE_SIGNATURE` still name HIS session because they were
inherited and nothing cleared them — and the test drives his desktop
successfully, quietly, exiting 0. **`tools/lib/session-guard.sh` is the
mechanism**; source it and call the one that fits:
`sg_require_nested` (die unless the target is NOT his session — call it right
after starting a nested compositor), `sg_require_offscreen`,
`sg_require_live_session` (for a harness that deliberately uses the live
compositor, so a stale signature aims it at nothing else), and
`sg_seat_snapshot` / `sg_seat_assert` to notice if a run took his focus or moved
his pointer, and `sg_pointer_pin CMD…` — the **only** sanctioned pointer warp,
for wrapping a call whose compositor-side side effect is a cursor snap. It
restores the position it read a moment before and cannot be aimed anywhere else.
Everything else here is read-only against his session.

The three nested harnesses (`home/prog/hyprvtb/tools/{nested-smoke,kinetic-test,hotswap-test}.sh`)
do **not** source this file and should stay that way: they are inside the
plugin's `src = ./.`, so editing them forces a plugin rebuild, a `main.cpp`
version bump and a live hot-swap. Their own `hc()` refusal is strictly stronger
anyway — it identifies the nested instance POSITIVELY, by its per-run config
path in `/proc/<pid>/cmdline`, so the signature it aims at can never be his, and
it re-checks on every single call rather than once.

**Placement is verified, not assumed.** `tools/sandbox.sh exec` checks after
every launch that the window actually landed on the headless output; one that
did not is closed and the run **aborts** rather than retrying in front of him.

**`tools/leak-check.sh` is the enforcement**, run by `preflight.sh`. Six states:
a dead compositor signature in the user manager, a stale `$XDG_RUNTIME_DIR/hypr/*`
lock whose PID is gone, a second Hyprland still running, a sandbox left standing,
**a test window (sandbox-tagged or probe-titled) mapped on a monitor he can see**,
and **his seat left where a harness put it** — focus on a test window or on an
off-screen monitor, or the pointer parked inside a `HEADLESS-*` output. It also
**notes a pointer sitting on the exact centre of a real monitor**, which is the
after-the-fact signature of an output removed without `sg_pointer_pin`. It
**warns and never fails** — every one of those states is one a real session can
legitimately be in, and a false failure blocking his rebuild would be worse than
the bug. Repair with `~/.config/scripts/hypr-session-env.sh --restore` and
`tools/sandbox.sh stop`.

**`tools/font-demo/font-demo.sh` is the one thing under `tools/` that opens a
window on his real screen on purpose** — a specimen for a person. It refuses to
run with no tty attached. Do not set `FONT_DEMO_ON_HIS_SCREEN=1`.

---

## Which machine you are on

**You are told, at session start. Do not guess, and do not re-derive it.** A
`SessionStart`/`SubagentStart` hook in `~/.claude/settings.json` runs
`~/.config/scripts/claude-host-id.sh` and prints the host, the flake attribute
and the correct rebuild command into your context before your first turn. The
script is generated per machine by `home/prog/claude-host-id.nix`. If you
somehow do not have that line, run `hostname` — never infer.

Why the hook exists: nothing else tells you. Your environment block carries the
working directory and a kernel version string and **no hostname**, so the only
tell that you are on the laptop is `…asahi…aarch64…` buried in that string.
Everything above this section is written from `top`'s point of view —
`sudo rebuild-top` presented as *the* rebuild command — so the default guess is
`top`, and on `book` that guess is wrong in a way that wastes a session.

**Never write the answer into a file.** Not into `docs/`, not into an
`AGENTS.md`, not into a memory:

- `~/.claude` syncs both ways between the machines (`home/srvs/claude-state.nix`)
  and so does `docs/` (`home/srvs/nix-docs.nix`). A note saying "you are on
  book" is read on `top`, where it is false. `top`'s agent then corrects it, the
  correction syncs back, and the two machines take turns being wrong.
- So **name the host** (`top` / `book`) in anything you write, or state the fact
  host-neutrally. `this machine`, `here`, `this box`, `you are on X` are all
  deixis: correct as you type them, false on arrival.

**Dispatching workers:** the hook covers subagents too, but a worker started
before a rebuild lands, or one you brief in a long prompt, still inherits your
framing. State the host in the dispatch prompt when the task touches rebuilds,
`sys/`, the compositor pin, or anything in `docs/HARDWARE.md`.

---

## Boundaries

**Always**

- Run `tools/preflight.sh`, then `sudo rebuild-top`, as the last step of any
  change here. Don't ask; don't leave it for the user.
- **Make the change on both `top` and `book`** unless he says it is
  machine-specific. If it genuinely cannot be host-neutral, land it and *say*
  which host misses out — never silently. See Conventions.
- `git commit` with an explicit pathspec: `git commit -m msg -- <paths>`.
- Commit **and push to `main`** after a working change. No branch, no PR.
- Edit the **nix source** of a mutable file (`Theme.qml`, `hyprland.lua`), never
  the live copy — the switch reconciles it. `tools/seed-drift.sh` after, as the
  tripwire.
- Bump the version string in `main.cpp` for every `hyprvtb` change.
- Tear down the worktree you were given once your commits are on
  `origin/main`.
- Update these `AGENTS.md` files when you change the architecture they
  describe.
- **Write a new reference/spec/inventory document under `docs/`, not at this
  repo root.** `~/nix` is a **public** repo; `docs/` is a private one. The test
  is *"would he mind a stranger reading this?"* — a document describing his
  desktop, his machine or his data fails it, credential or no credential.
  `DESIGN.md` and `HARDWARE.md` were both born here and both had to be moved
  (2026-07-27), which meant repathing ~120 citations across QML, Python, C++
  and every `AGENTS.md`. `AGENTS.md`, `README.md` and
  `home/prog/hyprvtb/PORTING.md` stay public on purpose — see
  `docs/README.md`.

**Ask first**

- Bumping the `hyprland` or `nixpkgs-quickshell` pins (see Conventions).
- Re-architecting the panel, the plugin, or the view-mode gesture.
- Anything that changes what happens at login/logout, or that would make the
  next login spawn windows.
- Deleting or reorganizing anything under `~` outside this repo.
- Committing when the tree holds changes you did not make and you cannot tell
  whose they are.

**Never**

- **Never run a reverting/destructive git command here** — no
  `git reset --hard`, `git checkout -- <file>`, `git restore`, `git stash`,
  `git clean`. The user leaves real uncommitted work in this tree.
- **Never `git commit` without `-- <paths>`.** The index is shared with other
  agents and the user; a pathspec-less commit takes *their* staged work too.
- **Never `hyprctl plugin load` / `unload`** for `hyprvtb`. It permanently
  erases the plugin's config keys and cannot be undone by `hyprctl reload`.
- **Never let a test touch his focus, pointer, clipboard, windows, audio,
  gamma or screen** — no test window on the real monitor, no screenshots, no
  driving the GUI. The whole list, and the detector that catches the residue,
  is under "Testing without interfering with the user" above.
- **Never call `save_session()` from a script.** It arms a window-spawning
  restore at the next login. It is a manual act (Meta+Ctrl+S) only.
- **Never edit the LIVE copy of a mutable file** (`~/.config/hypr/hyprland.lua`,
  `~/.config/quickshell/Theme.qml`). The next switch reconciles it from the nix
  source and your edit is gone (a copy lands in `~/.cache/seed-reconcile/`).
  Until 2026-08-05 the rule was the opposite — *edit both copies* — because
  those files were seeded once and a rebuild never updated them; that was the
  single most common way a change here appeared to do nothing, and
  `tools/seed-reconcile.sh` is what removed it.
- **Never `git add` a file that is already tracked** just so the rebuild sees
  it — flake eval reads the working tree. New files: `git add -N` only.
- **Never leave content staged** across a rebuild, a test run, or a question.
- **Never bump a pin alongside other changes** — its own commit.
- **Never hand-edit `~/.zshrc`** or anything else that is a `/nix/store`
  symlink; edit the source under `home/`.

---

## Where things live

- `docs/DESIGN.md` — **the design language.** Read before any visual change; see
  below. It lives in the **private** `docs/` repo (see `docs/` below), so a
  fresh clone of *this* repo does not contain it — the source comments across
  the panel, the apps and the plugin still cite it by that path.
- `docs/agents/his-voice.md` — **how he writes, and how he wants to be written
  to.** Two halves, one corpus. Part A is the register for every string the
  desktop SHOWS — toasts, labels, menu items, board bullets, error text: it is
  what `docs/DESIGN.md` §7.2's "lowercase" rule turns into once you are
  actually choosing words, and it exists because he read a set of toasts an
  agent had written and said they were *"too ai-coded"* (2026-08-22). Part B is
  the contract for ANSWERING him, of which the load-bearing rule is that
  landing work is **one line — what it does, pushed as `<sha>`** and nothing
  else unless there is a problem. Both are derived from the 1,061 prompts he
  has actually typed, not from taste; `tools/voice-corpus.py` is the extractor,
  so the reading can be redone rather than believed. Part B is also installed
  as the `lam` output style in `~/.claude`, which is the half that binds a
  reply; this file is the half an agent reads before writing a string.
- `docs/HARDWARE.md` — **what these two machines physically are**, and the command
  that measures each fact. CPU/thread count, RAM and swap, both GPUs (only one
  drives the screen), the board and its `nct6683` sensor chip, the real fan/pwm
  layout, the single 1080p display, the storage tiers, and how `top` and `book`
  differ. **Read it before you go measuring** — every fact in it is one an agent
  has already had to rediscover, once from a remembered fact that was wrong.
- `flake.nix` — inputs, the `top` NixOS configuration, and a standalone
  `homeConfigurations.air` for the second machine. The rationale for both
  pinned inputs lives here; read it before touching either.
- `hosts/top/` — machine-specific config for the primary host (full NixOS,
  x86_64-linux). `configuration.nix` holds the `my.aerotheme.enable` toggle.
- **`air`** — a MacBook Air on Fedora Asahi Remix (aarch64-linux), OS hostname
  `book`. Not NixOS: it gets only `home-manager` layered on the Fedora install,
  reusing `./lam.nix` and `home/` unchanged. There is no `hosts/air/`, and
  `sys/*` does not apply. Activate with
  `home-manager switch --flake /home/lam/nix#air`. (Everything about its
  *hardware* — and the full `top` vs `book` comparison — is in `docs/HARDWARE.md`;
  this bullet covers only what the repo does with it.)
- `sys/` — system-wide NixOS modules, auto-imported (see `umport`).
  `sys/options.nix` defines custom options; `sys/dsk/` the desktop sessions;
  `sys/hw/nvidia.nix` the GPU; `sys/gme/steam.nix` gaming.
- `home/` — home-manager config for `lam`, auto-imported. `home/pkgs/` package
  categories, `home/prog/` per-program config, `home/srvs/` user services.
- `lam.nix` — the home-manager entry point; imports `home/`.
- `apps/` — ten vendored Qt/QML apps (`filer`, `viewer`, `player`, `painter`,
  `surfer`, `askpass`, `reader`, `board`, `editor`, `slsk`) plus `pylib/`, the shared
  Python helpers — most importantly
  `vtbclient.py`, the hyprvtb titlebar-button socket bridge each app draws its
  chrome through.
    - **`apps/board/` is the program called `goetia`** — that is the only name it
      presents to him (window title, desktop entry, binary). The store it reads
      and writes is still `docs/board.<hostname>.md` (one board per host since
      2026-07-30), and every path and identifier is still `board*`: this directory, `boardctl.py`, `home/prog/board.nix`,
      `board-watch`. Prose keeps calling the FILE "the board".
    - **Board-facing text is written to the person at the machine, so it says
      `you`, never `he`/`him`.** Every bullet, note, question, option and
      `--if-unanswered` line rendered into `docs/board.<hostname>.md` is read
      by him and must address him as `you`. Prompts, comments and commit
      messages are internal and keep third person.
    - It lives **outside** `home/`/`sys/` on purpose: `umport` would try to
      eval an app's own `flake.nix` as a NixOS module. Nothing in the NixOS or
      home evaluation imports `apps/` — it is inert vendored source.
    - Each app runs its **live source** at `/home/lam/nix/apps/<name>/main.py`
      (absolute, valid on both machines), wrapped by `home/prog/<name>.nix`.
      A rebuild is only needed when a change adds a dependency or edits the
      `.nix` packaging.
    - `pylib` is found relatively (`HERE.parent / "pylib"`), so the `apps/`
      tree moves as a unit or not at all.
- `tools/` — the maintenance scripts the documented workflows depend on:
  `preflight.sh`, `seed-drift.sh` and `seed-reconcile.sh` (the pair that keeps
  the two runtime-mutable dotfiles level with their nix source — the reconciler
  runs from activation, the drift check is the tripwire behind it; **preflight
  must never block on drift the switch itself resolves**, which deadlocked
  every commit touching `hyprland.lua` until 2026-08-07 — harness
  `seed-gate-test.sh`),
  `prune-worktrees.sh` (aliased `wtprune`),
  `heavy-gate.sh` (**a heavy build never meets a loaded GPU backend without his
  say-so**: called by `rebuild-top` when the plan has local compiles in it, it
  raises a CRITICAL toast naming what is loaded — ComfyUI's resident weights,
  ollama's warm models and their size — with **Stop & rebuild** / **Rebuild
  anyway**. On *stop* it waits out any render in flight (never interrupts one),
  frees the weights, stops and runtime-masks `comfy-painter` and/or `ollama`,
  and puts back exactly what it took whatever happens to the build; on *anyway*,
  or on no answer inside the timeout, the build runs throttled beside them. A
  power-cycle on 2026-08-09 is why the gate exists, and his "ask me" is why it
  no longer decides alone. **A rebuild you trigger on the OTHER machine over
  ssh must pass `REBUILD_IGNORE_GPU=1`**: the toast lands on a screen nobody is
  sitting at, so the question cannot be answered and the gate spends its whole
  `REBUILD_ASK_TIMEOUT` (5 min by default) before falling through to "rebuild
  anyway" regardless — the same outcome, five minutes later [2026-08-24].
  `REBUILD_IGNORE_GPU=1` skips it,
  `REBUILD_ASK_TIMEOUT` sets the wait — and both only reach the wrapper because
  `sys/nixos-rebuild.nix` carries them across sudo's env reset by name. Until
  2026-08-25 it did not, so that documented incantation had never once worked.
  **The gate no longer asks a screen nobody is at either**: with no owner of
  `org.freedesktop.Notifications` on the user bus (top sits at the greeter for
  days) it answers `noask` at once and builds throttled, instead of holding the
  rebuild lock for the full timeout to reach the same place. **Its toast may never hold the rebuild
  lock**: `as_user` is `runuser -- env … notify-send`, so killing it at the
  timeout reaps runuser and ORPHANS the notify-send, which with no notification
  daemon on that host blocks on `-w` for ever — and it inherited the wrapper's
  flock on fd 9, so every later rebuild there queued behind a question nothing
  could display (found 17 minutes in, 2026-08-24). The toast now runs under
  `timeout` and with fd 9 closed. Harness `heavy-gate-test.sh`, which
  drives stub endpoints and never his backends; `heavy-gate.sh demo` is how HE
  raises the real toast),
  `sandbox.sh`, `leak-check.sh` (a test that leaked into his live session —
  residue *and* the live symptoms; preflight runs it) and `lib/session-guard.sh`
  (sourced by the harnesses; the anti-fall-through guards, see "Testing without
  interfering with the user"). Per-area **test harnesses** live here too and are named by
  whichever guide owns them (`claude-merge-test.sh`, `hotswap-test.sh`,
  `fan-harness.sh`, `media-lyrics-probe.sh`, …) — `ls tools/` rather than
  assume this list is complete.
  `boot-verify.sh` is **opt-in and not part of any rebuild**: it answers "will
  this configuration boot?" as far as anything short of a reboot can — static
  checks on the built toplevel (initrd modules for the nvme/ext4 root, NVIDIA
  built against the new kernel, ESP headroom) and, with `--vm`, a headless
  QEMU boot to `multi-user.target`. What it can and cannot prove, and the
  known-good ring below, are in `docs/agents/boot-safety.md`.
- **Known-good boot entries (`top` only).** `sys/boot-known-good.nix` keeps the
  last three generations *observed to boot* — a timer 3 minutes into boot
  records `/run/booted-system`, a permanent GC root under
  `/nix/var/nix/gcroots/known-good-boots/` puts it beyond both the root and the
  user `nix-collect-garbage`, and the recorder writes its own ESP copies and
  `known-good-*.conf` loader entries, which sit below the normal generation
  list as their own section and which the systemd-boot installer never
  garbage-collects. `known-good-boots list` to inspect; harness
  `tools/boot-known-good-test.sh`; full design in `docs/agents/boot-safety.md`.
  NixOS-only, so `book` does not get it.
- `sounds/` — **git submodule** → `github.com/meatcrowning/vista-sounds`
  (PRIVATE). The Vista event `.wav`s are Microsoft's and must not live in this
  public tree. `home/srvs/vista-sounds.nix` exposes the checkout at the runtime
  path via an out-of-store symlink (`~/.local/share/sounds/vista →
  /home/lam/nix/sounds`), so a plain `git pull` picks up new sounds
  with no rebuild. **Cloning on a new machine needs `--recurse-submodules`**
  (or `git submodule update --init` afterwards) plus GitHub auth, or the
  directory is empty.
- `docs/` — the repo's working notes (plans, roadmaps, runbooks). **Its own git
  repo against the PRIVATE remote `github.com/meatcrowning/nix-docs`, living
  inside this public checkout and listed in `.gitignore`** — so `git` run from
  `~/nix` does not see these files at all. Commit from inside `docs/`, or let
  the timer do it. **Two shelves inside it**: `docs/` root is what *he* might
  read — the state of a feature, findings about his machine or his data,
  backlogs waiting on his verdict; `docs/agents/` is what only an agent reads —
  runbooks, procedures, one-off impact analyses, raw research. Would he open it
  to learn something, or would an agent open it to execute something?
  `docs/README.md` states the rule and indexes both. Syncs both ways with book
  every 5 min via
  `home/srvs/nix-docs.nix`, which reuses `claude-memory-sync.sh` verbatim — that
  script is parametrized by `CM_SYNC_REPO`/`REMOTE`/`LOG`/`SEED`/`LABEL`/
  `MAX_MB` (docs arms the size cap at 25 MB — its only protection with no
  gitignore; a 118 MB hermes export committed on 2026-08-03 wedged every push
  on GitHub's 100 MB limit), so a
  second systemd user unit was all it took. Log `~/.cache/nix-docs-sync.log`;
  force a run with `systemctl --user start nix-docs-sync.service`.
  **ONE BOARD PER HOST, and nothing merges them.** Since 2026-07-30 the store
  is `docs/board.top.md` on `top` and `docs/board.book.md` on `book`; each
  host's app, watcher and reminder read and write only their own, and the other
  file is carried purely as a backup and a history. His words: *"i actually want
  to change it so neither board on top or air syncs … i dont want that
  overwriting … to overwrite anything i do on air. commits obviously will stay
  synced."* The FILES still sync like everything else here — what is gone is any
  writer on one machine touching the other machine's board. The name comes from
  the OS hostname (`top` / `book`), never the flake attribute (`top` / `air`),
  because every runtime writer has only the hostname; `boardparse.board_path()`
  states the rule once and `ensure_board()` seeds an empty board on a machine
  that has never had one.
  **Prose here still conflicts loudly for a human — a board does not.** A board
  is a store with an unattended writer and a GUI, and an unresolved conflict
  does not merely flag that file: it aborts the tick and stops docs/ syncing in
  either direction until someone notices. `board.top.md` / `board.book.md`
  (and the pre-split `board.md`, for old history) carry `merge=boardrecent` —
  seeded `.gitattributes`, registered by `nix-docs-setup.sh`, named one by one
  rather than globbed so `agents/board-watch.md` stays prose. The driver runs
  the real 3-way merge first and only a genuine collision falls back to **the
  more recent side wins, whole** — his rule, 2026-07-29, and symmetric, so
  neither host is privileged. Losing sides stay in history. With one writer per
  file that path should now never be taken; it is the net for a hand edit on the
  wrong machine. Harness: `tools/board-merge-test.sh` — re-run it after touching
  the driver, the attributes or the registration, since a missing registration
  makes the rule inert with no error.
  Deliberately **not** a submodule: `git
  pull` does not update submodule contents, so the other machine would read a
  stale runbook. There are now four callers of that script (claude-state,
  nix-docs, oracle-skills — see below — and its own tests); a fifth **must**
  override `CM_SYNC_SEED` — its default installs `~/.claude`'s denylist
  `.gitignore`, whose exclusions mean nothing in another tree while that tree's
  own secrets go unguarded. `DESIGN.md` and `HARDWARE.md` live in here;
  a few docs stay outside on purpose and `docs/README.md` says which and why.
- `home/srvs/oracle-skills.nix` + `oracle-skills-files/` — **chatter's skills,
  tool manifests, subagent definitions and measured per-model KV costs, synced
  both ways between `top` and `book`.** They live in chatter's own runtime dir
  (`~/.local/share/oracle/{skills,agents,tools}` + `ctxfit.json`),
  not `~/.claude`, and were machine-local until 2026-08-23 — a skill written on
  one host simply did not exist on the other, and `book` had neither directory.
  Same engine as the two above (`claude-memory-sync.sh`, 5-min timer, private
  remote `meatcrowning/oracle-skills`). Two things make it safe: the repo root
  is the WHOLE runtime dir — `sessions/`, `memory/`, `jobs/`, `sandbox/`,
  `images/` sit beside the three shared dirs — so the seeded `.gitignore` is an
  **allowlist** that can never widen by accident, and `*.md` + `*.json` merge
  through the boards' recency driver (`board-recent-merge.sh`, registered by
  `oracle-skills-setup.sh`) because chatter's `make_skill` writes these
  unattended on both machines and an unresolved conflict would wedge the sync.
  The machine-built `youtube-content` venv is excluded by name. Log
  `~/.cache/oracle-skills-sync.log`; force a run with
  `systemctl --user start oracle-skills-sync.service`.
- `home/srvs/hypr-env.nix` + `hypr-env-files/hypr-session-env.sh` — **a user
  unit must never inherit the systemd user manager's
  `HYPRLAND_INSTANCE_SIGNATURE` / `WAYLAND_DISPLAY`.** Hyprland *itself* (not
  our config) runs `systemctl --user import-environment DISPLAY WAYLAND_DISPLAY
  HYPRLAND_INSTANCE_SIGNATURE …` at every startup and the matching
  `unset-environment` at clean exit. That store is manager-global and has no
  owner, so **every** Hyprland on the box writes over the last one — including
  every nested test compositor an agent starts, which the harnesses tear down
  with `SIGKILL`, so it never gives the values back. Measured on `top`
  2026-07-28: the manager named a compositor dead for an hour, on `wayland-2`,
  while the session ran on `wayland-1`. A unit that shells out to `hyprctl`
  under that env fails to connect **and still exits 0** — a service that
  silently does nothing. Wrap the ExecStart of any unit that needs the
  compositor: `%h/.config/scripts/hypr-session-env.sh %h/.config/scripts/x.sh`
  (`wal-set.service` is the only one so far). It resolves the live instance from
  `$XDG_RUNTIME_DIR/hypr/*/hyprland.lock` — alive PID + live socket, preferring
  the compositor that is not itself a Wayland client — instead of believing what
  it was handed. `--check` is preflight's detector, `--restore` repairs the
  manager *and* the D-Bus activation store (what an activated
  `xdg-desktop-portal-hyprland` reads, which unit wrapping cannot reach) and is
  called by all three nested harnesses on teardown.
- `home/srvs/ai-warden.nix` + `ai-warden-files/ai-warden.py` — **the referee
  between chatter's ollama and painter's ComfyUI**, `top` only. They share 31
  GiB and each wants most of it: measured 2026-08-22 with nothing unusual
  running, ollama alone held **24.7 GiB** for one `qwen3.6:35b-a3b`, and a
  painter render landing on top of that does not fail, it **livelocks** the box
  (mechanism in `sys/oomd.nix`). `tools/heavy-gate.sh` already refereed a
  *rebuild* against these two; nothing refereed them against **each other**.
  This does, by **admission control** rather than by reacting to pressure —
  reacting is too late, the spike IS the load. Both apps call `/reserve` before
  they load or queue (`apps/pylib/warden.py`), and the warden **frees, never
  stops** (ollama takes a zero `keep_alive`, comfy takes `POST /free`; both
  daemons stay up), **never interrupts work in flight** (a busy other side is a
  refusal with a reason, not a cut render), and **acts on its own judgement and
  says so** (a toast naming what went — his call, 2026-08-22; a question per
  turn would be intolerable). A watchdog on `MemAvailable` + PSI is the net
  behind it, for memory admission control cannot see coming.
    - **Read the cgroup, not `/api/ps`.** Measured: ollama's endpoint returned
      `{"models":[]}` while `llama-server` already held 14.4 GiB RSS and 10.7
      GiB of VRAM — it is blind for the whole duration of a load, which is
      exactly the window a freeze happens in. `memory.current` was correct
      throughout, so every footprint is `max(API, cgroup)`.
    - **A refusal is measured against what will sit in RAM, not the file
      size.** A model's tag size is its whole file, but the layers ollama
      offloads live in VRAM and the pages it read them through are file-backed
      cache `MemAvailable` already counts as free — so charging the file against
      RAM double-counts. On 2026-08-23 that refused his own 22.2G model with
      painter shut and 24.4G free, for being 0.3G short. `hard` now subtracts
      what free VRAM can hold; `need` (which decides whether to FREE) still
      counts the whole file, because over-freeing is cheap and the freeze this
      daemon exists for came from under-estimating.
    - **RAM refuses; VRAM only tidies — but the tidying has to HAPPEN.** A
      VRAM shortfall degrades a job (ollama offloads, comfy errors); only RAM
      takes the desktop with it. What made that a dead letter until 2026-08-25
      was `busy()`: it read the DEVICE's `gpu_util`, and one GPU has two
      tenants, so comfy's own model loading came back as "chatter looks busy"
      and protected the 9.7 GiB of resident weights the render needed. It now
      reads **ollama's own cgroup CPU clock** (`ollama_working`), and a comfy
      reserve that cannot fit on the card waits an advisory-busy ollama out
      (`IDLE_WAIT`) before freeing it. A live LEASE is still never touched —
      that is a claim, `busy` is an inference, and rule 2 protects the claim.
    - **Two floors, on purpose.** `RAM_FLOOR` (6G) decides whether to *free* —
      generous, because freeing is cheap. `HARD_FLOOR` (2.5G) is the only one a
      *refusal* is measured against, because a refusal is chatter telling him
      no; measuring his own 23.9 GiB model against the 6G floor would have
      banned it outright.
    - **A long job says it is still working; it does not ask again.** `/renew`
      extends a lease already held and can never take, free or toast — which is
      what lets a lease be SHORT and heartbeat-renewed rather than long and
      taken once, so a caller that dies mid-render costs the other side its
      beat interval and not its ceiling. chatter's video generation is up to an
      hour and uses it (`apps/oracle/main.py`, `_make_media`), and it also
      gives its OWN weights back before asking for room — the warden never
      interrupts work in flight, so without that a chatter holding 22 GiB would
      refuse every generation it asked for itself.
    - **It must be RUNNING and REACHABLE, or fail-open makes it a no-op.**
      Both halves were broken until 2026-08-24 and neither said a word: the
      unit was `WantedBy=graphical-session.target`, so it died whenever nobody
      was sitting at `top` — while ollama (a system unit) and comfy-painter (a
      user unit needing no session) stayed up and were driven from book — and
      `ollama-tunnel.sh` forwarded 11434 but not **8199**, so every reserve
      chatter made from book was an instant unarbitrated yes. Measured that
      evening: warden dead since 20:47, and a `make_video` from book at 23:41
      landed on a GPU still holding gemma4-qat:12b —
      `torch.OutOfMemoryError … Free (according to CUDA): 9.62 MiB`, with
      nothing in its own log because it was never asked. It is now
      `WantedBy=default.target` and the tunnel forwards both ports. **A
      fail-open daemon is one you have to check is alive**
      (`systemctl --user is-active ai-warden`, `ai-warden status`), because
      down and working look identical from the app.
    - **What it freed is drawn where HE is.** The warden's toast lands on
      `top`; from book that is a screen nobody is looking at, so `Warden.last`
      carries the whole answer back and chatter says
      `unloaded your model to make room on the gpu` in the tool line itself.
    - **Fail open everywhere.** Kill switch `~/.local/state/ai-warden/off`; a
      dead or wedged daemon is an immediate yes. Log `~/.cache/ai-warden.log`,
      `ai-warden status` for the picture, harness `tools/ai-warden-test.py`.
    - `sys/ai/ollama.nix` carries the other half: `sys/oomd.nix` arms oomd on
      the **user** slices only, so ollama — a **system** unit and the biggest
      memory holder on the box — had nothing watching it at all. It now has a
      `MemoryHigh` throttle and a `ManagedOOMMemoryPressure` policy, plus
      `OLLAMA_MAX_LOADED_MODELS=1` / `OLLAMA_NUM_PARALLEL=1` so one chat cannot
      cost two sets of weights and N KV caches.
- `home/srvs/board-watch.nix` + `board-watch-files/` — **acts on his answers to
  this host's board (`docs/board.<hostname>.md`) without waiting to be told
  about them.** A `path` unit on the
  file plus a 5-minute timer; when a decision becomes *newly answered* it spawns
  one headless `claude -p` on that one decision. Two rules from him, both
  settled: the agent **works, and since 2026-07-29 it may rebuild and reload
  too** — at its own judgement, any hour, under "When it is okay to rebuild or
  hot-reload" above and nothing looser (it used to be forbidden outright and
  left such work undone with a note) — and it fires **only while he is at the
  machine**: locked or away, the answer is queued, not dropped. The filter is semantic, never authorship: an agent
  moving an item to LANDED, or the docs sync pulling somebody's prose edit, adds
  no answer and must not fire. It runs on **both** machines, each watching its
  OWN board, so one answer cannot be seen twice in the first place. HOST
  AFFINITY survives as belt-and-braces — the board app stamps which machine he
  answered on and each watcher fires only on its own stamp (an unstamped answer,
  i.e. a hand edit, belongs to `top`) — which is what keeps a board restored
  from the other host's synced copy harmless. Typed input needs no rule: the
  inbox is machine-local. No automatic
  takeover — re-answer on the other machine to hand an item over. Kill switch:
  `touch ~/.local/state/board-watch/off`. Log `~/.cache/board-watch.log`;
  harness `tools/board-watch-test.py`; runbook `docs/agents/board-watch.md`.
- `home/srvs/board-reminder.nix` + `board-reminder-files/board-reminder.py` —
  **writes a bullet onto this host's board when a condition he named comes true,
  once, and then never again.** A quarter-hourly timer, no path unit (nothing
  writes a file when the condition changes). The one reminder in it fires after
  his **weekly Claude usage window resets** — the instant is read, not guessed,
  from Claude Code's own cache in `~/.claude.json`
  (`cachedUsageUtilization.utilization.limits[kind=weekly_all].resets_at`;
  that file is NOT under `~/.claude`, so it does not sync). A reset counts as
  observed either when the clock passes the recorded target or when the cached
  window moves past it; unreadable cache is a no-op that retries. **One bullet
  per board, written by the host it belongs to**: with the boards per-host there
  is nothing to arbitrate, so the old `top`-owns-the-write / 24h-grace pair is
  gone; the bullet's marker is still looked for in the live board first, as the
  idempotence backstop. Self-disarms via
  `~/.local/state/board-reminder/<id>.done` (delete to re-arm). Harness
  `tools/board-reminder-test.py`.
- `home/srvs/repo-updates.nix` + `repo-updates-files/repo-updates.py` — **"the
  other machine pushed to `~/nix`", as a toast with buttons on it.** `docs/` and
  `~/.claude` sync themselves; the flake cannot, because pulling it is only half
  of landing it and the other half switches the machine he is sitting at. So a
  daemon checks `origin/main` at session start (started from `hyprland.lua`, so
  a boot and a login both count), on resume from suspend — detected by
  `CLOCK_BOOTTIME` outrunning `CLOCK_MONOTONIC`, which needs no system-bus match
  rule and therefore works on book — on a **once-a-minute `git ls-remote`
  peek** (one round trip, no objects, no local writes; the full fetch-and-diff
  runs only when that sha is new, which is what took the toast's latency from
  "up to half an hour" to a minute) and on a 30-minute backstop poll. The
  persistent toast carries the commit count, a couple of subjects and what
  applying will **cost**, read off the diff: a moved compositor pin means a
  from-source Hyprland build on book *and* no live plugin hot-swap on either
  host (next login), while an `apps/`-only change means no rebuild at all.
  `Pull & apply` pulls `--ff-only`, rebuilds through the host's own wrapper
  (which owns preflight and the shared lock) and reloads what can be reloaded,
  under **one toast raised the instant the button is clicked and morphed in
  place until the result** — each step named, with a **progress bar** for it
  (the `value` hint; the panel's NotificationCard draws it, `docs/DESIGN.md`
  §8.1). The bar is measured where a count exists (paths built against nix's
  own printed plan, git's "Receiving objects: N%") and creeps toward 90% where
  none does (the evaluation). `--demo-progress` shows the whole thing without
  pulling anything. `Dismiss` stays quiet until a NEWER sha lands. It never stashes, resets or checks out — a tree that blocks the
  fast-forward is reported and the pull abandoned. `nix-pull [check|apply]` is
  the same code by hand, and what the toast names when the panel's
  `notifActions` setting is off. Kill switch
  `~/.local/state/repo-updates/off`; log `~/.cache/repo-updates.log`; harness
  `tools/repo-updates-test.py`.
- `home/srvs/board-notify.nix` + `board-notify-files/board-notify.py` — **a toast
  when a finishing worker's completion lands on this host's board**, unless
  goetia is already the focused window. It is `Type=simple` — a persistent
  daemon, unlike its two siblings, because the one thing it needs cannot be a
  one-shot: goetia focus is read from Hyprland's **event socket** (never
  `hyprctl activewindow`, which lies — the `hyprctl-activewindow-lies` memory)
  and the socket only pushes on change. It watches the same file board-watch
  does, dedupes on fingerprints exactly like board-watch's newly-answered
  semantics (first run seeds, fires nothing; a docs-sync pull re-fires nothing)
  and matches the worker result **by its tag, whatever the word** — currently
  `ENACTED` (renamed from `COMPLETION` 2026-08-01), both accepted, so the
  rename cannot stop it. Kill switch `~/.local/state/board-notify/off`. Harness
  `tools/board-notify-test.py`.
- `home/srvs/board-spend-export.nix` — **mints this host's hermes spirit spend
  into `~/nix/docs/spend.<host>.json` quarterly-hourly**, so the board's spend
  section can show BOTH machines' hermes rows (the Claude side already combines
  — transcripts sync — but `~/.hermes/state.db` does not). The writer is live
  source at `apps/board/tools/hermes-spend-export.py`; the docs sync carries
  the file to the other host, and `boardspend` folds the other host's export
  into the ranked list, the daily chart and window filters — never its own
  export beside the live ledger, so nothing double counts. Unchanged content is
  not rewritten, so a quiet host mints no docs commits. Harness
  `tools/board-test.py` → `test_hermes_spend_export`.
- `home/srvs/lid.nix` + `lid-files/lid-close.sh` — **what closing the lid does,
  on `book` only** (`top` is a desktop; the module is gated on `host == "air"`).
  The setting is `lidClose` in `~/.config/quickshell/settings.json`
  (`suspend` | `lock` | `blank` | `nothing`, default `suspend`), drawn on the
  Settings window's Lock & Power page and re-read on every lid event, so a
  change applies to the next close with nothing restarted. **logind is kept out
  of the lid by a user service holding a `handle-lid-switch` block inhibitor**
  rather than by `/etc/systemd/logind.conf`, which on book is Fedora system
  state this repo cannot write and a reinstall would lose — no root, nothing to
  redo by hand. Hyprland's own `switch:on/off:` binds (`hyprland.lua`, gated on
  `host.laptop`) call the script. The trade: while that unit runs, a lid closed
  outside a Hyprland session does nothing; `systemctl --user stop
  lid-inhibit.service` gives Fedora's default suspend-on-close back.
- `home/srvs/claude-state.nix` + `claude-state-files/` — two-way sync of **the
  whole of `~/.claude`** between `top` and `book` via the PRIVATE repo
  `github.com/meatcrowning/claude-state`: memories, `orchestrator-briefing.md`,
  `plans/`, `file-history/`, and every session transcript. `~/.claude` *is* the
  checkout — in place, no copying — driven by the `claude-state-sync.timer` user
  unit every 5 min (log: `~/.cache/claude-state-sync.log`; force a run with
  `systemctl --user start claude-state-sync.service`). Being under `home/` it
  deploys to book automatically; that machine needs only
  `home-manager switch --flake ~/nix#air` plus a `gh auth login` (the git
  credential helper is `!gh auth git-credential`). **Treat that remote as
  internal documents** — it is a verbatim record of whatever was on screen.
  Three invariants:
  the `.gitignore` is a **denylist** (secrets and machine-local runtime state
  by name) — the inverse of the allowlist it replaced, so it *can* widen by
  accident and `CM_SYNC_MAX_MB` exists to catch that; `.gitattributes` gives
  every file shape a merge that cannot wedge an unattended timer *or* resolve
  wrong — `merge=union` for prose `*.md` and append-only `*.jsonl`,
  `merge=ours` for `*.json` (union would emit invalid JSON), and
  `merge=claudemd` for `**/memory/*.md`, a memory being frontmatter plus prose
  that union merged *structurally* into a document with two `description:` keys,
  silently. That driver
  (`claude-state-files/claude-memory-merge.sh`, registered by premigrate,
  tested by `tools/claude-merge-test.sh`) resolves a memory by last-writer-wins
  on Claude Code's own `modified:` stamp and dedupes `MEMORY.md`'s index lines,
  so **no merge here needs a human afterwards** — re-run that test after
  touching the driver, the rule, or the registration, since a missing
  registration falls back to union with no error. All seeded from nix
  on every run — edit them in `claude-state-files/`, not in the live repo.
  Practical consequences: **a memory is shared infrastructure**, so say which
  host a fact is specific to — and a file referenced by an absolute path from a
  memory is now actually there on the other machine, which was the bug that
  widened this scope (a briefing one directory above the old repo root never
  synced, silently). It supersedes `claude-memory.nix`; the old
  `claude-memories` remote survives as a read-only archive, and
  `claude-state-premigrate.sh` retires the nested repo on each machine by
  itself.

### `docs/DESIGN.md` — read it before you draw ANYTHING

**`docs/DESIGN.md` is the design language: how everything on this
desktop looks and behaves.** Typography and the pixel font's traps, the
wallpaper-derived palette, spacing and corners, motion timing, titlebar button
vocabulary, menus, tooltips, list rows, drag feedback, and the "never offer an
action that can silently fail" rule.

It is **not optional reading and not per-area**. The panel, the five apps you
did not touch, the compositor plugin and the window config are four codebases
and one desktop, and the user should not have to restate his preferences on
every feature — that is the whole reason the file exists. **Any change that puts
pixels on the screen reads it first, whichever tree it lands in.** If you change
how something looks, update it in the same commit.

### Nested guides — read the one nearest what you are editing

| Editing | Read |
|---|---|
| **Anything visual, anywhere** | **`docs/DESIGN.md`** (always), then the row below |
| **Any string the desktop SHOWS** — a toast, a label, a menu item, a board bullet, an error | **`docs/agents/his-voice.md`** Part A |
| **Anything about the metal** — cores, RAM, GPU, sensors, fans, disks, the display, or which host you are on | **`docs/HARDWARE.md`** (before you measure) |
| The Quickshell panel (`home/prog/quickshell-files/*.qml`) | `home/prog/quickshell-files/AGENTS.md` |
| Hyprland config, the `hyprvtb` plugin, the sandbox | `home/prog/AGENTS.md` |
| Bumping the compositor pin / plugin ABI seam | `home/prog/hyprvtb/PORTING.md` |
| Any of the ten Qt apps | `apps/AGENTS.md`, then `apps/<name>/AGENTS.md` |

`PORTING.md` is cited by ten referrers including `checkPhase` failure messages
and lives inside the plugin's derivation source — moving it forces a plugin
rebuild and a live hot-swap. Leave it where it is.

Same reason, one live exception: the six `DESIGN.md` citations inside
`home/prog/hyprvtb/*.cpp`/`*.hpp` still say the bare name rather than
`docs/DESIGN.md`. Every file there is part of the derivation's `src`, so
rewriting a *comment* changes the source hash and forces a plugin rebuild, a
`main.cpp` version bump and a live compositor hot-swap. They mean the same
file; read `docs/DESIGN.md`. Fold the repath into the next hyprvtb change that
bumps the version anyway.

---

## Conventions

**Recursive imports (`umport`).** Defined in `sys/default.nix` and
`home/default.nix`; each auto-imports every
`.nix` file found recursively beneath them. Adding a file anywhere in those
trees is sufficient — no `imports` list to edit — including for `air`, which
consumes the same `home/` tree via `lam.nix`. (Only `.nix` files; docs and
scripts alongside them are ignored.)

**Per-host branching (`host`).** `flake.nix` threads `host = "top" | "air"`
into every `home/*.nix` module via `specialArgs`/`extraSpecialArgs` — take it
as a module arg: `{ host, ... }:`. Use this, not a per-host file, for the rare
line that must differ (`home/prog/zsh.nix` rebuild aliases,
`home/plasma.nix`'s `Xwayland.Scale`, `home/prog/hypr-host.nix`'s generated
`host.lua`). Everything else in `home/` is shared verbatim — that is the point
of the split. Packages missing on aarch64 (x86_64-only binaries: `vcv-rack`,
`pcsx2`, `vintagestory`, `google-chrome`, `wineWow64Packages`, `spotify`,
`dwarf-fortress-packages`) are gated with
`lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [...]`, since the real
constraint is architecture, not the machine.

**Both machines by default.** The two paragraphs above are the *mechanism*;
this is the rule. A change here is for `top` **and** `book` unless he says it
is machine-specific — he should not have to say "and on the laptop too".

- `sys/` and `hosts/top/` are NixOS-only, so anything expressible only there
  is machine-specific by construction. Do it, and tell him book does not get
  it — with the host named.
- When something must differ per host, use the `host` module arg or a platform
  predicate. Not a new per-host file; there is no `hosts/air/` and there should
  not be one.
- Missing on aarch64 is an **architecture** constraint, not a preference:
  gate on `pkgs.stdenv.hostPlatform.isx86_64` and say so in those words.
- **Never write host deixis into a file.** `~/nix` and `docs/` both sync to the
  other host, where `this machine` is false — name `top` / `book`. (See "Which
  machine you are on".)

The failure mode to check for: `home/` is evaluated by *both* hosts, so a
change that ends up top-only by accident — a package dropped into an existing
`isx86_64` list that is not actually x86-only, or a path, unit or binary that
exists only on `top` — is **silent** on book. Nothing warns; the config just
does nothing there. (Adding an x86-only package *ungated* is the loud version:
book's `home-manager switch` fails, but only when he next runs it.) Whenever
you touch a conditional, look at the branch you are not on.

**Two pins; everything else rolls.** `nixpkgs` tracks `nixos-unstable`, but the
compositor (`hyprland`, an exact upstream tag) and the shell
(`nixpkgs-quickshell`, a whole nixpkgs frozen to one revision) do not — so a
routine `nix flake update` can no longer leave the session with no titlebars or
no panel. Everything else — mesa, the NVIDIA driver, the kernel, Qt/PySide6,
kitty, Plasma — still rolls and still can break things, so `nixos-rebuild
build` before `switch` and keep the previous generation in mind. A third,
**temporary** pin `hyprland-air` (v0.55.4) exists because book runs Fedora
Asahi's rpm compositor; see `home/prog/AGENTS.md` and
`docs/book-hyprvtb-version-bridge.md`.

**Aerotheme Plasma toggle.** `my.aerotheme.enable` (defined in
`sys/options.nix`, set in `hosts/top/configuration.nix`) switches between stock
Plasma 6 and the Windows-themed `aerothemeplasma`; `sys/dsk/plasma.nix` handles
the conditional session and `aeroshell` activation.

---

## Off-LAN: the tailnet

`air` reaches `top` from any network over Tailscale. `top`'s side is
`sys/net/tailscale.nix`; MagicDNS name is `top`, operator is `lam` on both (so
`tailscale up`/`status` need no sudo — that is how an agent drives it).

**Every hole is an allowlist, per interface.** `share.nix` scopes the LAN holes
to `enp12s0` and `kdeconnect.nix` scopes 1714-1764 there too — hand-rolled
because `programs.kdeconnect.enable` opens that range on *every* interface with
no opt-out, so the module is deliberately unused. `tailscale.nix` opens exactly
**22 (ssh) and 445 (SMB)** on
`tailscale0`. It is deliberately *not* a trusted interface — that setting
published every listener on the box, including OpenRGB's unauthenticated SDK
server on `0.0.0.0:6742`. **Anything loopback-pinned stays loopback-pinned**:
ComfyUI (`127.0.0.1:8188`) is reached from air through
`apps/painter/tools/comfy-tunnel.sh`, an ssh port-forward, never a new
listener. Adding a port here is a security decision — take it deliberately.

**`book`'s side is not in this repo and cannot be.** `tailscaled` is a system
daemon and book has home-manager only, so it is Fedora state: `dnf install
tailscale`, `systemctl enable --now tailscaled`,
`sudo tailscale set --operator=lam`, then `tailscale up`. Redo by hand after a
reinstall. Book's `/etc/fstab` mounts the library from **`//top/aud`** (the
MagicDNS name), not `//top.local/aud` — `.local` is mDNS and answers only at
home, so the old name meant no music off-LAN. That mount therefore depends on
the tailnet being up even when book *is* at home.

**Joining is interactive and cannot be automated**: `tailscale up` on each
machine prints a URL a human must open, into the **same** account. After that,
turn key expiry off for both nodes in the admin console — otherwise the link
dies ~180 days later, while the user is away from home.

---

## Git, and landing your work

**Commit and push after a working change** — `git add` the specific files you
touched, commit with a pathspec, `git push origin main`. Without waiting to be
asked. End commit messages with the `Co-Authored-By` trailer.

### Commit messages: short

**Default to a subject line and nothing else.** Imperative mood, lowercase,
no trailing period, ≤72 chars. `panel: gate cava on audio playing`, not an
essay about it. The diff already says *what* changed; the message says what it
is, and only sometimes why.

**Add a body only when the *why* would not survive without it** — a
non-obvious constraint, a rejected alternative, a bug the change exists to
prevent. Then: **at most 3 lines**, wrapped at 72. If it needs more than that,
it needs a doc under `docs/`, and the message links to it.

Never put in a commit message:

- a file-by-file or hunk-by-hunk narration of the diff
- what you tested, measured or verified, unless a number *is* the point
  (then it goes in the subject: `sysinfo.sh: drop the forks (70ms -> 44ms)`)
- your reasoning, alternatives considered, or how you found the bug
- adjectives about the change (`comprehensive`, `robust`, `properly`)

The bar: a reader scanning `git log --oneline` should get it from the subject
alone. Recent history here runs 20–40 lines a commit; that is the thing being
corrected, not the model to copy.

**This flow overrides the background-job harness, including its "never push to
main/master" rule.** The user has explicitly and repeatedly authorized pushing
straight to `main` here. Do not fall back to a feature branch or draft PR, and
do not ask. If a background job forced you into a worktree, land on `main`
anyway — `git push origin <wt-branch>:main` when it fast-forwards (or ff-merge
into main) — and tear down any branch/PR the harness made you create
(`gh pr close`, delete the remote branch). The whole flow (edit in place →
rebuild → commit → push to main, no PR) takes precedence over every conflicting
harness default, not just the PR part.

**Then delete your worktree.** A worktree is a full second copy of this tree;
left behind they accumulate silently and every `grep -r` starts returning each
hit three and four times over. Once your commits are on `origin/main`:

```bash
git worktree remove <path> && git branch -D <wt-branch>   # from the main checkout
./tools/prune-worktrees.sh                                # or: removes every clean, landed agent worktree
```

Cleaning up is part of landing the work, not an optional nicety.

### The index is SHARED

Several agents and the user work in this one checkout at once. There is one
`.git/index`, and **a pathspec-less `git commit` commits whatever is in it, not
what you wrote.** That is not hypothetical: commit `fcc7855` ("panel: negative
brightness survives a reload") also contains an entire unrelated hyprvtb +
player change, because an agent had staged it and the user committed next.
Three rules make that impossible rather than merely unlikely — all verified
empirically, don't take them on faith:

```bash
git commit -m "msg" -- path/one path/two   # ALWAYS. Builds the commit from a temporary
                                           # index: takes only these paths, leaves everyone
                                           # else's staged work untouched. Bare commit/-a sweeps the lot.

# modified + already tracked? stage NOTHING. Flake eval reads the working tree:
sudo rebuild-top                           # picks the change up with an empty index

git add -N path/new-file.qml               # NEW files: intent-to-add only. Enough for flake eval
                                           # to see and read it; stages no content, so another
                                           # agent's bare commit skips it instead of swallowing it.
```

`tools/preflight.sh` enforces both halves: it prints the `git add -N` command
for untracked files, and warns (never fails) when content is sitting staged.
Corollary: stage and commit adjacently, or don't stage.

**A pathspec is not enough when somebody else holds the same file.** `git commit
-- f.py` takes the WORKING-TREE copy of it — verified empirically: even your own
partially-staged hunks are ignored and the whole working tree is committed, their
half-finished edits and debug probes included. That is what happened at 9c1f477:
boardwork.py held another spirit's decision-unit WIP in the working tree, and
the pathspec commit swept both agents' work into one commit. **Commit through
`tools/git-commit.sh`, not a bare `git commit`.** It is the enforcement half of
"confirm every hunk is yours":

- Default mode: prints the exact diff that will land (the whole working-tree
  copy), and REFUSES any path whose uncommitted change is large enough to be
  plausibly not entirely yours — because a pathspec commit cannot separate
  hunks. Narrow the pathspec, `--hunks` it, or `--yes-file <path>` when you've
  reviewed the printed diff and accept sweeping that file.
- `tools/git-commit.sh -m "subj" --hunks -- path`: `git add -p` only the hunks
  you own, then commits the index
  — your hunks land, the other spirit's WIP stays behind, unstaged, exactly
  as you found it. (An index commit, safe only because it first asserts the
  index holds nothing but your own staged hunks.)
- It refuses bare/`-a` invocations mechanically, so the shared index is never
  swept by accident.

`tools/preflight.sh` adds the warn (never fail) complement: a file whose
uncommitted diff vs HEAD is large gets flagged as the mixed-WIP smell before a
rebuild, so the hazard is visible even if you commit by hand. `tools/git-commit-test.sh`
exercises both halves in a throwaway repo — re-run it after touching the helper
or that preflight block.


### Never clobber the user's own edits

The user routinely hand-edits files here and may leave those changes
uncommitted. **Run `git -C ~/nix status` before committing or pushing.** If the
tree holds changes you did not make, they are almost certainly theirs — do not
assume they are stale or safe to discard, do not reach for any of the
destructive commands in Boundaries, and scope your commit to your own paths. If
you cannot tell what is yours, ask.

---

## Maintaining these files

1. **Keep them updated.** Substantial architectural changes, new top-level
   directories, or new major features/options must be reflected here — or, if
   they belong to one area, in that area's nested `AGENTS.md`.
2. **Put detail at the right level.** The root file is orientation, commands,
   boundaries and cross-cutting rules. Anything that only matters once you are
   already editing a particular tree belongs in that tree's file. If a section
   here grows past a screen or two, that is the signal to split it out.
3. **Rule first, story second.** Lead with the instruction; keep the incident
   that produced it, but as the supporting clause. Every prohibition here was
   paid for once already, so the provenance stays — it is what stops the fix
   being "improved" back out.
4. **Respect the structure.** System-level changes go in `sys/`, user-level in
   `home/`; prefer a small focused new `.nix` file over bloating
   `configuration.nix` or `lam.nix`. Adding a file to those trees is enough for
   it to be imported.
