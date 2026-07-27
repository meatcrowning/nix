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
/usr/bin/python3 apps/askpass/tools/askpass-selftest.py   # the three contracts, headless
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
