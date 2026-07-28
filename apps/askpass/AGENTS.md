# AGENTS.md — `askpass`

The `SUDO_ASKPASS` password dialog. Packaged by `home/prog/askpass.nix`, which
also owns the wrapper `sudo-askpass` that `SUDO_ASKPASS` actually points at.

**`sudo -A` is load-bearing infrastructure in this repo** — every agent runs
root commands through it, from shells with no tty. Treat anything here as
touching that, and verify before you land.

---

## Why it exists at all

ksshaskpass drew a stock Plasma dialog, so it inherited whatever KDE colour
scheme the machine happened to have: passable on `top`, **light-themed on book**
(Fedora Asahi, which has none of our Plasma theming). Restyling it was not on
the table — the fix was to stop borrowing someone else's dialog. This one paints
every pixel from the same live wal palette the panel and the other apps read
(`~/.config/quickshell/Theme.qml`, parsed by `main.py`'s `Palette`), so both
hosts are identical and nothing depends on Plasma being installed.

---

## The password path — the only thing that really matters

```
QML TextInput (echoMode Password)  ->  Sudo.accept(text)  ->  os.write(fd 1)  ->  sudo
```

and **nowhere else**. Not argv, not a file, not a log, not a shell variable —
the wrapper runs the dialog with stdout inherited straight from sudo's pipe
rather than capturing it, so `set -x`, a trap or `ps` can never see it.
`Sudo.accept` writes on the raw fd and then `os._exit`s, so no interpreter
teardown, atexit hook or Qt destructor can put anything else on stdout after
it. **Every diagnostic goes to stderr. Never print to stdout from this app.**

## Exit codes are a CONTRACT with the wrapper

| code | meaning | wrapper does |
| --- | --- | --- |
| 0 | password written to stdout | pass through |
| 1 | cancelled / window closed — no output | pass through |
| 3 | dialog could not be displayed | **fall back to ksshaskpass** |
| other | crash | fall back to ksshaskpass |

**1 and 3 must stay distinct.** A cancel is a decision and must not trigger the
fallback; an import/QML/GL failure must, or a broken PySide6 (on book it comes
from Fedora's `python3-pyside6`, which an OS upgrade can break independently of
this repo) would leave the machine with no way to authenticate at all. That is
why ksshaskpass is still installed in `askpass.nix` — it is the parachute, not
dead weight.

## Telling the user WHY root is being asked for — and FOR WHAT

Two lines in the inset box, from two different places, and the dialog invents
neither.

**The reason is the caller's words.** One short clause, in the user's terms:

```bash
SUDO_ASKPASS_REASON="rebuilding the flake" sudo -A nixos-rebuild switch ...
```

**The command is read out of `/proc`, and cannot be forgotten.** `sudo_command()`
in `main.py` walks the parent chain from `getppid()` to the first process whose
`comm` is `sudo` — the dialog is always its (grand)child: askpass helper ← the
`sudo-askpass` wrapper ← sudo — reads that process's `cmdline`, strips sudo's own
flags (`_SUDO_ARG_OPTS` covers the ones that eat the next token) and shows what
is left.

That second line exists because the first one was **theoretically fine and
empirically useless**. `$SUDO_ASKPASS_REASON` does reach this process when it is
set — verified end to end with a stub askpass under a real `sudo -k -A`, the var
arrives intact — but a sweep of every `sudo -A` an agent has actually run in this
repo found **not one** that set it. The instruction had been in three files for
as long as the dialog has existed. So the prompt said `NO REASON GIVEN` every
single time, and a privilege dialog that can never say what it is for is not
worth reading. Anything derived from the caller's discipline was going to decay
the same way; the process tree does not need cooperation.

Keep setting the reason anyway — it says *why*, which argv cannot. But treat the
command line as the load-bearing half.

All three displayed strings — the reason, the derived command, and sudo's own
argv[1] prompt — are **untrusted**, and a password dialog whose body text is
caller-controlled is a phishing surface. (The command is untrusted text but
*trustworthy evidence*: it is the thing being authorised rather than a claim
about it, which is exactly why a lying reason cannot hide behind it.) Two
defences, and **neither may be removed**:

- `sanitize()` in `main.py` drops C0/C1 control characters, collapses
  newlines/tabs to spaces, and clamps length (240 chars, 120 for the prompt), so
  nothing can escape its line, forge a blank region, or grow the window enough to
  push the password field off-screen. `maximumLineCount` (4 for the reason, 3 for
  the command) bounds it again in QML. Measured offscreen, settled: 520x259 with
  neither line, 520x312 with a command, and 520x346 for a hostile 400-char reason
  plus a 450-char command — the ceiling.
  The derived command is additionally sanitized `ascii_only=True`: it is a path,
  not prose, and one non-ASCII byte would drop the whole line onto a fallback
  font (see the layout traps below).
- `PixelText.qml` sets `textFormat: Text.PlainText`. QML's `Text` defaults to
  `AutoText`, which **sniffs for HTML and interprets it** — markup must be shown,
  never rendered.

The reason is also walled off in its own inset box under a caption naming whose
words they are, so it can never read as the dialog's own voice.

## `SUDO_ASKPASS` must stay a STABLE path

`home/prog/askpass.nix` points it at `~/.local/bin/sudo-askpass`, a
home-manager symlink — **not** at the wrapper's `/nix/store` path. A process
reads its environment once, and this repo's agents hold shells open across many
rebuilds. When the dialog was first replaced, 31 live processes still held the
previous generation's store path and kept popping the OLD ksshaskpass dialog;
the user reported "it still looks like the light theme" and was exactly right.
A store path in `SUDO_ASKPASS` means that recurs on every rebuild — and lets
`nix-collect-garbage` break `sudo -A` outright by deleting a wrapper that live
shells still reference.

A stable path is only half of it, because `home.sessionVariables` lands in
`hm-session-vars.sh`, **which guards itself with `__HM_SESS_VARS_SOURCED`**. A
long-lived process that sourced it once has the guard set in its environment, so
every shell it spawns inherits the guard, skips the file, and keeps the stale
value. So `askpass.nix` also sets `programs.zsh.envExtra`, exporting
`SUDO_ASKPASS` **unconditionally from `.zshenv`** — which zsh sources on every
invocation, interactive or not, outside every guard. That is the half that
rescues sessions already running: the next command an existing agent shell runs
already picks up the current wrapper, with no restart.

The residual gap is a process that invokes `sudo -A` **without spawning a shell**
(a direct `execve`, a `subprocess` with `shell=False`). Those keep whatever they
were started with. Agents here go through zsh, so in practice they are covered.

## Never run `sudo -A` as a test

It pops a **real** password dialog on the user's screen and demands their root
password while they are doing something else — and if you feed it a stub, sudo
burns real authentication attempts and logs failures against their account. This
happened: `sudo[1791493]: lam : 3 incorrect password attempts ; COMMAND=/usr/sbin/true`,
with the user meta-dragging the window away mid-task. **Verify without sudo:**

```bash
python3 apps/askpass/tools/askpass-selftest.py   # the contracts
zsh -c 'echo $SUDO_ASKPASS'                      # what a new shell resolves
readlink -f /home/lam/.local/bin/sudo-askpass    # which wrapper that is
```

(The selftest re-execs itself under the interpreter baked into the
`vista-askpass` wrapper when the one it was started with has no PySide6 — which
is every plain `python3` on `top`. It used to be documented as
`/usr/bin/python3`, a path that only exists on book: on `top` that reported two
spurious FAILs and three PASSes that only "passed" because a missing PySide6 is
what the `broken` case tests for.)

That covers the whole chain except sudo's own `read`, which is sudo's contract,
not ours, and does not need re-proving at the user's expense.

## The app-id `vista-askpass` is load-bearing in THREE places

Rename it and you must change all three together:

1. `apps/askpass/main.py` — `setApplicationName` / `setDesktopFileName`.
2. `home/prog/hypr-files/hyprland.lua` (**both copies** — seed-once) — the
   `askpass-dim` window rule: `dim_around`, `center`, `pin`.
3. `home/prog/quickshell-files/Askpass.qml` — the panel's own scrim switch.

(3) exists because `dim_around` only covers Hyprland's **window** pass. The
Quickshell bar is a layer-shell surface on the `top` layer, which renders
*above* that dim, so the desktop went dark and the bar stayed bright. The panel
therefore paints its own scrim over `barBody` at the same strength
(`decoration:dim_strength`, 0.5). The panel **self-observes** via the Wayland
foreign-toplevel list — there is deliberately **no IPC call from this app into
the panel**, so a dead or wedged panel can never break `sudo -A`; the worst it
can do is leave the bar undimmed.

---

## Verifying — never on the user's screen

```bash
python3 apps/askpass/tools/askpass-selftest.py   # the three contracts, headless
```

It runs the real `main.py` under `QT_QPA_PLATFORM=offscreen`, drives the QML
from Python and asserts: accept → exit 0 with stdout *exactly* the password;
cancel → exit 1 with stdout empty; `PySide6` unimportable → exit 3 with stdout
empty. **Run it after any change to `main.py` or `Main.qml`.**

To see the dialog against the real compositor without it appearing in front of
the user, put it on the off-screen monitor and read the geometry back:

```bash
tools/sandbox.sh start
tools/sandbox.sh exec "$(command -v vista-askpass)"     # absolute path: the
      # compositor's PATH predates your home-manager switch
hyprctl clients -j        # expect class vista-askpass, floating+pinned (the rule)
tools/sandbox.sh stop
```

Note this briefly dims the user's bar, because the panel is doing exactly what
it is supposed to.

**The dialog is excluded from hyprvtb's geometry memory** (`vtbNeverRemembersGeometry`
in `hyprvtb/main.cpp`, ≥2.88) — in all three directions: not restored on open,
not saved on close, and dropped when `geometry.tsv` is read, so a stale entry
self-cleans at the next plugin load instead of being rewritten forever by
`vtbSaveGeometry` (which rewrites the whole map whenever *any* window closes).
That last part is why deleting the line by hand was not enough. A modal must
land where its window rule puts it, every time.

## It has NO titlebar — and that is why Cancel/Esc are load-bearing

hyprvtb draws no vertical bar on this window at all (`vtbNeverDecorates()` in
`hyprvtb/main.cpp`, ≥2.94; docs/DESIGN.md §7.5). Every button a bar offers is one a
fixed-size, centred, pinned, never-remembered modal must not have, and the only
one that did anything — [x] — is what `Cancel` and `Esc` already do. **So the
QML's Cancel button and `Keys.onEscapePressed` are now the ONLY ways to
dismiss it from the keyboard or mouse.** Deleting either would leave a dialog
that can only be answered, which is a wedged `sudo` for anyone who opened it by
mistake. The exit-code contract above is unchanged: a compositor-side close is
still `onClosing` → `Sudo.cancel()` → exit 1, verified end to end by closing the
real window on the sandbox monitor.

It keeps the hard drop shadow (`CVtbShadowDeco`) — a shadow is the window's, not
its chrome. Bar-less is a state the plugin already had for the scratchpad, so
everything keyed off `bars` skips this window too: no session-snapshot entry, no
geometry memory, no open reveal, and `close_all()` at logout does not click an
[x] it does not have.

Two things fall out that are easy to break:

- **Nothing may widen this window's box by `totalBarW()`.** The shadow layer and
  its damage box ask `vtbHasBar()` now; before 2.94 they assumed a bar was there
  to span, which would have put a bar's width of shadow past the right edge with
  nothing drawn above it.
- **The plugin focuses it explicitly.** On this desktop a newly opened floating
  window is handed the keyboard by the open reveal (`beginRollReveal()` →
  `Hl::focusWindow`), and a bar-less window plays no reveal. `onNewWindow` does
  the focus half itself instead. Measured, not assumed: with the bar, a
  sandbox-launched dialog emitted `activewindow>>vista-askpass`; bar-less
  without that line, it emitted nothing.

Verify (no sudo, nothing on his screen):

```bash
tools/sandbox.sh start
tools/sandbox.sh exec "$(command -v vista-askpass)" 'test:'
hyprctl decorations "class:vista-askpass"   # HyprvtbShadow, and NO Hyprvtb
tools/sandbox.sh stop
```

## Layout traps already paid for

- **Do not write `minimumHeight: height`.** The height binding then references
  itself and Qt resolves the loop by collapsing the window — measured at
  520x**32**, i.e. a sliver with the entire body clipped. Compute the size into
  its own `readonly property` and have `height`/`minimumHeight`/`maximumHeight`
  all read that.
- **No horizontal anchors on a direct child of a `Column`** — a positioner
  refuses them. The right-aligned button row is wrapped in a plain `Item`.
- **ASCII only in every label**, and `passwordCharacter: "*"`. "More Perfect DOS
  VGA" has no bullet, ellipsis, minus sign or arrows; one missing glyph drops the
  whole line onto a fallback font with a different ascent and it clips.
