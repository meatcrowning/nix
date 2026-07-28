# DESIGN.md — the desktop's design language

**Read this before you draw anything.** It is the single source of truth for how
this desktop *looks and behaves*, across the four codebases that put pixels on
the screen:

| surface | tree |
|---|---|
| the panel, wallpaper, desktop widgets, popups, OSD | `home/prog/quickshell-files/` |
| window chrome — titlebars, tooltips, shadows, roll/open/close animation | `home/prog/hyprvtb/` (C++) |
| window borders, gaps, corners, window animations | `home/prog/hypr-files/hyprland.lua` |
| the six apps — filer, viewer, player, painter, surfer, askpass | `apps/` |

They are four codebases and one desktop. **A user cannot tell which one drew a
tooltip, so they must all draw the same tooltip.** Those four trees — and the six
apps named individually — are the *scope tokens* this file uses to say how far a
rule reaches. **Read [§0](#0-scope--here-or-everywhere) before you decide that
something applies to only one of them.**

## Why this file exists — in his words

> *"i want to figure out which visual features and decisions of this desktop
> were made by me — for example how all program split buttons should look the
> same, or all the font should be formatted / styled the same. those sorts of
> things. basically i want every new feature implimented or every new program
> created to all look the same without me having to specify it every or nearly
> every time."*

That is the brief. **Everything below is a default you inherit, not a menu you
choose from.** If you are about to ask "what should this look like?", the answer
is in here; if it genuinely is not, follow §1 and then add it.

The area guides (`home/prog/quickshell-files/AGENTS.md`, `home/prog/AGENTS.md`,
`apps/AGENTS.md`, `apps/<name>/AGENTS.md`) own the *mechanics* — how to get an
edit live, what crashes the panel, which file to touch. **This file owns the
look.** Where an area guide states a visual rule in more detail, it wins for its
area; nothing here contradicts one.

**Provenance is marked, because you are allowed to argue with some of it:**

- **[his]** — he said it, or a commit records him correcting an agent who did
  otherwise. Verbatim quotes are his, typos and all — they are the evidence.
  **Do not "improve" these.**
- **[code]** — a convention the code already follows consistently, written down
  and promoted to a rule so it stops being re-decided per file.
- Agent *proposals* are not in the body of this document. They are in
  [Open questions](#open-questions) at the end. **Do not promote one yourself.**

---

## Contents

| § | what it settles |
|---|---|
| [0. Scope](#0-scope--here-or-everywhere) | "here" or "everywhere?" — the three scope marks, and why unmarked means desktop-global |
| [1. First principles](#1-first-principles) | the handful of ideas every other section is a consequence of |
| [2. Typography](#2-typography) | the pixel font, its missing glyphs, sizes, weights, casing |
| [3. Colour](#3-colour) | the wallpaper-derived palette, what may hard-code a colour, and what may not |
| [4. Geometry](#4-geometry--corners-borders-shadows) | corners, borders, shadows |
| [5. Density and layout](#5-density-and-layout) | spacing scale, padding, alignment, how tight is tight |
| [6. Motion](#6-motion) | durations, easings, what animates and what must not |
| [7. Menus, popups and dialogs](#7-menus-popups-and-dialogs) | one menu look across four codebases |
| [8. Tooltips](#8-tooltips) | one tooltip look across four codebases |
| [9. Lists, rows, columns and graphs](#9-lists-rows-columns-and-graphs) | row height, selection, headers, sparklines and meters |
| [10. Honest affordances](#10-honest-affordances) | a control that is drawn is a control that works |
| [11. Focus, pointer and input](#11-focus-pointer-and-input) | hover, press, focus rings, cursors, scroll feel |
| [12. Window chrome and the titlebar](#12-window-chrome-and-the-titlebar) | the vertical titlebar, its button glyphs, stacked title |
| [13. Drag and drop](#13-drag-and-drop) | what a drag looks like while it is happening |
| [14. Cross-app continuity and persistence](#14-cross-app-continuity-and-persistence) | what an app must remember, and what it must not |
| [15. The wallpaper and the desktop surface](#15-the-wallpaper-and-the-desktop-surface-panel) | `[panel]` |
| [16. Web pages as a design surface](#16-web-pages-as-a-design-surface-surfer) | `[surfer]` |
| [17. Sound](#17-sound) | the Vista event set, and when a sound is allowed |
| [18. Desktop-wide laws](#18-desktop-wide-laws-and-things-this-desktop-deliberately-does-not-have) | the short list of absolutes, and the things this desktop deliberately does NOT have |
| [19. Where the shared pieces live](#19-where-the-shared-pieces-live) | the actual files — reuse before you write |
| [20. Recorded exceptions](#20-recorded-exceptions) | places that break a rule on purpose, with the reason |
| [Open questions](#open-questions) | agent proposals awaiting his verdict. **Not rules yet.** |
| [Maintaining this file](#maintaining-this-file) | how to add to it without breaking it |

Also: [Why this file exists — in his words](#why-this-file-exists--in-his-words) (above).

---

## 0. Scope — "here" or "everywhere?"

Every rule in this file has a blast radius, and guessing it wrong is the single
failure this document exists to end. So scope is notated, in three marks.

**Unmarked means DESKTOP-GLOBAL.** A rule with no scope tag binds the panel,
`hyprvtb`, `hyprland.lua` and all six apps. There is no `[global]` tag — that is
the default, and marking it would only add noise to 95% of the file. The
notation is bookkeeping; **the default itself is [his]**, and it is the brief
quoted above: *"every new feature implimented or every new program created to
all look the same without me having to specify it every or nearly every time."*

**`[panel]` `[hyprvtb]` `[hyprland]` `[filer]` `[viewer]` `[player]`
`[painter]` `[surfer]` `[askpass]` `[apps]` `[top]` `[air]`** — on a heading or
a bullet, that rule is scoped to that surface, because that surface is the only
one that *has* the thing it describes. **A scope tag says where the subject
exists; it is not permission for that surface to look different.**

**`[except <surface>: reason]`** — a surface that legitimately breaks a global
rule. Every one of these is also a row in
[§20 Recorded exceptions](#20-recorded-exceptions).

### 0.1 The default is global, and here is the tie-break

His standing requirement is that a new feature or a new program **looks like the
rest without him having to specify it again**. Therefore:

**Assume every preference he states is desktop-global.** When he names one
program he is describing the desktop and using that program as the example. He
has had to widen an agent's too-narrow fix himself at least three times — the
split-button glyphs (§12.1), the queue slide timing (*"this is another thing
that should always happen when we do a new feature or program etc design
language"*, §6.2) and the glyph map (*"yes id like px() wired through the others
as well"*, §2.3). **Scoping a fix to where he happened to be pointing is the
most common way work here has to be done twice.**

When he does not say which he means, decide in this order and stop at the first
answer:

1. **Does the same thing already exist on another surface?** If yes it is
   global — change them all. This is the first question of any visual change,
   not the last.
2. **Is his stated reason about that program's own subject matter?** Reason
   about the *subject*, not the app he named: "the cover art should bleed to the
   window edge" is about album art and is `[player]`; "tooltips should slide out"
   is about tooltips and is global.
3. **Could the two surfaces sit side by side on one screen?** They all can. If
   the disagreement would be visible in one glance, it is global.
4. **Still unsure: apply it globally, and say so in your report.**
   Over-applying is cheap — it converges the desktop, and he can name the one
   exception in a sentence. Under-applying costs him a second ask about the same
   thing.

**One asymmetry, and it is the only one: ADDING a convention defaults to global,
REMOVING a capability does not.** *"remove the close button in the inner
titlebar"* (§7.4) is not a licence to strip close buttons desktop-wide. A
subtraction stays where he pointed unless he widens it.

**Cross-host scope is settled and needs no tie-break:** *"i basically want both
computers to look and operate the same"* [his]. `[top]`/`[air]` mark hardware
facts only — screen scale, battery vs GPU sensors. Nothing else.

### 0.2 A divergence must be RECORDED to exist

**A program may differ, but only on the record.** If you write code that breaks a
rule in this file — or you find code that already does and conclude it is right — add a
row to [§20](#20-recorded-exceptions) **in the same commit**, with its scope and
its reason. An unrecorded difference is indistinguishable from a bug: the next
agent either "fixes" it back out, or copies it into a seventh surface as
precedent. Both have happened.

**Do not record your own taste as his decision.** If you think a surface *should*
differ and he has not said so, it is a `candidate`: add the §20 row marked
`candidate` and raise it in [Open questions](#open-questions). Only he promotes a
candidate. This is the same discipline §"Maintaining this file" already applies
to rules — §20 is where it applies to exceptions.

---

## 1. First principles

Seven ideas generate almost everything below. When this file does not cover your
case, reason from these.

1. **One desktop, four codebases — and a capability added to one app belongs in
   all of them.** [his] Same function, same glyph, same behaviour, everywhere:
   *"the split buttons for both surfer and filer should be the same as with
   kitty, `|` and `_`"*; *"maybe add split view functionality to surfer as
   well … i meant split view in filer lol … viewer should also get a split view
   too"*. The same holds for **motion**: *"this is another thing that should
   always happen when we do a new feature or program etc design language"*
   (§6.2). Where two trees cannot share code, they carry deliberate parallel
   implementations of one rule — **retune both, or the desktop stops feeling
   like one thing.**

   **He has now had to ask for this after the fact twice in one day** — once
   for split-button glyphs, once for animation timing. Each time, the answer
   already existed somewhere else in the tree. Treat "does this already exist
   elsewhere on the desktop?" as the first question of any new feature, not the
   last.
2. **kitty is the typographic reference.** [his, 7 turns across 5 sessions]
   *"the margins in the desktop (EVERYTHING that's not kitty; pannels, widgets,
   programs. etc.) between lines is wider than in kitty. i want it to match
   kitty's."* — and when offered "close enough": *"yeah i want kitty exact"*.
3. **No system-themed windows.** [his] Anything that can appear on this
   desktop is rebuilt in the desktop's own idiom, including a privileged
   password prompt: *"i want to have it entirely recreated to match the
   desktop. style formatting and all."* That is the charter for why six
   vendored apps exist at all.
4. **Density: zero-gap, edge-to-edge, no dead space.** [his, 8 turns across 5
   sessions] Whitespace is not a design element here; it is waste — with one
   hard floor (§5.3).
5. **A state change must look like a state change, not a re-entry.** [his, the
   single most-repeated rule in the corpus] Reloads, theme changes and agent
   hot-reloads must be *visually undetectable*. See §6.1.
6. **Never offer an action that can silently fail, and never report a change
   that did not happen.** [his] *"neither the stars or the heart does anything —
   or at least nothing happens that the user can see"*; *"it reports it in the
   osd but doesnt change the screen gamma"*. See §10.
7. **Measure; don't reason. But he does the looking.** [his] All visual,
   animation and interaction judgement is his. Agents verify by IPC, logs,
   offscreen renders and font tables — never by screenshotting his screen, never
   by opening a window on it. Two commits state this as method: *"This gesture
   cannot be judged from a log line and I have now mis-diagnosed it twice by
   reasoning instead of measuring"* (`7d437ff`), and the unlit-colour choice was
   *"established by rendering the glyph data out to a PNG rather than by making
   the user click through the modes"* (`52eda63`).

   **The instruments have traps of their own, and they are written down where
   each instrument lives — read that before you trust a surprising number.**
   Three have now cost an agent real time more than once: `hyprctl activewindow`
   never clears, so it cannot mean "focused on nothing"; `hyprctl eval` returns
   no values, only `ok`; and **a leftover `tools/sandbox.sh` headless monitor
   gives the panel a second `DockGrid`, which wins the shared table and makes
   `qs ipc call live tiles` report another monitor's panel height** — check
   `hyprctl monitors` first (`quickshell-files/AGENTS.md`, "a measuring
   instrument has to be harder to poison than the thing it measures";
   `home/prog/AGENTS.md` for the compositor ones). Measuring is only better than
   reasoning if you know what your instrument is actually reading.
**And one more, about scope:** *"i basically want both computers to look and
operate the same"* [his]. Per-host divergence is limited to hardware facts —
screen scaling, battery vs GPU sensors. Appearance and behaviour are identical
on `top` and `book`.

---

## 2. Typography

### 2.1 One font, kitty's size, kitty's line box

**More Perfect DOS VGA at 15px, everywhere — panel, widgets, runner, titlebar,
all six apps.** [his]

kitty runs `font_size 11pt`, which at 96 DPI rasterises to an 8x15 cell, so
**15px is the number that makes desktop text and terminal text the same size on
screen** (`8b1ee99`, `142ee92`, both 16→15). The font's native cell is 16px, so
15 is deliberately a touch off-grid — matching kitty outranks matching the
pixel grid.

**A text-only row is exactly one font cell tall, with zero inter-row gap.**
[his] The whole "kitty-tight" pass exists because of one complaint —
*"look at how there is a TON of space between the rows of text… can you make it
so that spacing between rows is like kitty's? i believe the vast majority of the
desktop's UI has this issue"* — and one override of the agent's compromise:
`2d03640`'s message says outright *"drop the small padding from last commit —
user wants exact kitty line packing."* Rejected values, in order: 22px fixed,
`fontSize+4`, `fontSize+2`, then finally `fontSize` flat. Icon- and
control-driven heights are left alone; where an icon forced a row taller, the
**icon** shrank (launcher, 22→18px).

He came back to this unprompted twice more, days later — *"can you do a full
pass through the repo for the font thing?"*, *"i dont think that happened for
the titlebar text but also double check everything else too"*. **Check any new
text surface against kitty before shipping it.**

### 2.2 `PixelText`, never a bare `Text`

[code — seven copies, the panel's and one per app]

```qml
textFormat: Text.PlainText            // §2.3 — a security rule, not a style one
font.family: Theme.font
font.pixelSize: Theme.fontSize        // PIXELS, never points
font.hintingPreference: Font.PreferFullHinting
renderType: Text.NativeRendering      // FreeType at device pixels
antialiasing: false
lineHeight: Theme.fontSize            // == kitty's cell
lineHeightMode: Text.FixedHeight
```

- **`Text.NativeRendering`.** QML's default `QtRendering` is a distance-field
  renderer for smooth scalable fonts; it antialiases a bitmap font into a blurry
  mush that looks nothing like the terminal.
- **Pixel sizes, never points** — points get DPI-scaled to a fractional pixel
  height that lands between the font's design grid and reintroduces blur.
- **`lineHeight` pinned to the font size.** Qt rounds ascent and descent up
  *separately* (at 15px: 11.25→12 plus 3.75→4 = 16px), so unpinned multi-line
  text leads 1px wider than kitty's cell and compounds down a paragraph.
  **Under `FixedHeight`, `lineHeight` is a PIXEL COUNT** — a leftover
  `lineHeight: 1.1` made a two-line tooltip 15.2px tall, i.e. its lines drew on
  top of each other (`21534ca`).
- **No bold, ever.** [code — `7da096d`] The font ships Regular only; Qt's
  synthetic bold "smears and reads as a heavier, slightly larger, different
  typeface next to the regular glyphs". Bold emphasis is a deliberately accepted
  loss.
- **`Text.elide` is FINE with this font — do not hand-roll an ASCII elide.**
  [code — measured] Qt substitutes three ASCII periods by itself when the
  family has no U+2026, so an elided `PixelText` never takes the fallback
  ascent. Measured against the real font at 15px:
  `QFontMetrics.elidedText(…, Qt.ElideRight)` came back
  `'a very long ...'` — `0x2e 0x2e 0x2e`, no U+2026 anywhere. This entry
  previously said elide was *banned* (from `7584956`, where the real fault was
  an uneven-row report) and it was wrong: it contradicted
  `quickshell-files/AGENTS.md`, which had measured the same thing, and it
  condemned ~45 correct call sites across the panel and all six apps. **The
  substitution depends on the family lacking the glyph**, so it is a property of
  this font, not of Qt in general — check again if the font is ever changed.
- **Where you clip instead of eliding, the item height is `fontSize + 2`** —
  the glyph ink is 16px (12 ascent + 4 descent), so a tighter box clips
  descenders.

### 2.3 The font's cmap is short — and a missing glyph CLIPS THE LINE

The most expensive trap on this desktop; it has been fixed at least seven times.

More Perfect DOS VGA has `° · ■ █` and Latin-1. It does **not** have
`… − — – ↑ ↓ ▲ ▼ ▴ ▾ • ♫ ' ' " " ™ © ® × ø`. A string containing one makes Qt
fall back to another font **for that one character**; the line takes the
fallback's taller ascent; under `FixedHeight` that ascent has nowhere to go, so
**the whole line is pushed down inside its row and clipped along the bottom.**
His report: *"i think characters like ' ruin the formatting of the queue of the
media player widget on the panel"*.

**Glyph coverage is a LAYOUT concern, not a cosmetic one.** Three rules, for
three kinds of text:

- **Hardcoded UI strings are written to suit the font: ASCII only.** [his/code]
  `...` not `…`, `-` not `−`/`—`, `'` not `'`, `*` not `•`. `askpass` uses
  `passwordCharacter: "*"`. `48a6ff3` was a systematic cmap sweep that found
  fifteen more in the panel alone.
- **Text from OUTSIDE is mapped at INGEST, systemically.** [his] `Glyphs.px()`
  maps the punctuation, spaces, arrows and symbols the font lacks onto ASCII.
  When the first fix was scoped to one widget he widened it himself: *"yes id
  like px() wired through the others as well."* Map at the ingest point where
  there is one (one pass per data change, not one per delegate per scroll); map
  at the display site only where the model belongs to Qt or Quickshell.
- **`Glyphs.px()` is DISPLAY ONLY — a safety rule.** [code] Nothing
  identifying goes through it: a task cell's raw title is the join key and the
  dispatch address, a path is handed to `gio`/`mv`/`rm`, a pid is what `kill()`
  signals, a launcher's `entry.command` is the argv. The sharp edges are
  **prefill sites** — a rename dialog and an inline drive-label editor both put
  a value in front of the user that is written back by `mv` and by a real
  filesystem relabel. Map either and the desktop quietly renames the user's file
  or their volume. Both carry a comment saying so; leave them.
- It is a **lookup table, not "strip anything the font lacks"** — ~830 of the
  library's 11k tracks are CJK or fullwidth with no ASCII form, and a title
  turned into question marks is worse than one in the wrong font. That limit is
  recorded, not hidden.

**Audit by asking the FONT, not by eye.** `fc-list :charset=` and
`QRawFont.supportsCharacter` both lie (the latter answers `True` for characters
it maps to glyph 0):

```python
QRawFont(".../MorePerfectDOSVGA.ttf", 15).glyphIndexesForString(ch)[0] == 0
```

### 2.4 Paired glyphs: one glyph mirrored, never two characters

[his] *"the up arrow of the unrolled queue … should be the same glyph of the
down arrow … just upside down. also the up arrow isnt actually inside the roll
button like the down arrow even though it should be"*

`^` is not `v` upside down here: from the glyf table `v` is 1792 units tall on
the baseline while `^` is 1024 hard against the ascender, so in a 14px strip one
caret's ink landed on rows 0-2 — reading as *outside* the button — against rows
4-10 for the other. Use the same glyph with `Scale { yScale: -1 }` about its
centre, and **round the item's `y`**: an integer origin keeps `NativeRendering`
crisp under the flip. Both states must sit identically inside their button.
(`1b28dc1`, `e84df13`. The same instinct settled the titlebar's roll button
`>>` → `<<` while shaded, months earlier.)

### 2.5 In a vertical text run, lay the colon flat

[code — `fc40581`] The titlebar's text is rotated. *"In a column of upright
letters an upright ':' is two dots reading top-down — the same axis the text
runs in — so it reads as two more characters instead of a separator, and it
costs a whole cell."* Draw it as two pips side by side. He asked for the same
in the player: *"can you rotate the : in the elapsed time / total time
indicator? so it is horizontal instead of vertical and then that section takes
up less space."*

### 2.6 Plain text, always — this is a security rule

**`textFormat: Text.PlainText` on every label.** [code — `b6840f9`, `7bce570`]
QML's `Text` defaults to `AutoText`, which *sniffs* for HTML and renders it.
Almost everything this desktop draws is a string from somewhere else — window
titles, filenames, ID3 tags, page titles, notification bodies, process names, a
`JS alert()` body, a portal caller's dialog title — so the default hands any one
of them a markup renderer, and an `<img src="http://…">` in a notification body
is a read beacon. `Notifications.plain()` strips tags at ingest but then
*unescapes entities*, so `&lt;img&gt;` survives the strip and would be reborn as
markup at the draw site. **Both halves are required.**

### 2.7 The size is ONE setting, and layout must survive it

**Nothing draws text at a literal pixel size, and nothing sizes a box that
holds text with a literal either.** [code] The Settings window's *font family*
and *font size* controls are the whole desktop's, not the panel's: the panel's
`Theme.qml` binds to `SettingsStore.d.fontFamily`/`.fontSize`, and each app's
`Theme.qml` binds to `DeskStyle`, a context property whose Python side
(`apps/pylib/deskstyle.py`) reads the very same
`~/.config/quickshell/settings.json`. One slider moves panel, titlebars and all
six apps.

It is deliberately **not** parsed out of the panel's live `Theme.qml` the way
the palette is. `wal-set.sh` writes colours there as literals, but the two font
keys are QML *expressions* — parsing them yields the string
"SettingsStore.d.fontSize". `settings.json` is what `SettingsStore` persists, so
reading it is reading the same value, not inventing a second source of truth.

The slider's range is **10-24px** (`SetPgAppearance.qml`), i.e. 0.67x to 1.6x of
the default 15. The pixel font is monospace: **advance = `round(0.533 *
fontSize)`** (8px at 15) and **glyph ink = `fontSize + 1`**. So:

- a plain text row is `Theme.fontSize` tall (§2.1), a `clip: true` one
  `Theme.fontSize + 2` (§2.2) — never a literal;
- a column holding *N* known characters needs `N * Theme.fontSize * 8 / 15`, or
  better, an `implicitWidth`-driven binding. A fixed width `W` first clips at
  `fontSize = 1.875 * W / N`;
- a **pixel budget standing in for a character count** — `parent.width - 130`,
  `width > 620`, a `minimumWidth` chosen so N cells fit — is the same bug
  written less obviously, and breaks at the same point.

**What is still literal, audited at 10 / 15 / 24px:** painter derives *nothing*
from `Theme.fontSize` and is the one app with real breakage above ~17px (its
`Picker` rows, `Spin` widths and `ModelPicker` reserves); player, filer and
surfer each keep a handful (player's `Stars`, its track-number column and the
`height: 15` right-hand cluster; filer's 146px timestamp columns and the
`620`/`470` thresholds; the `height: 22` buttons all three share). askpass,
viewer and `qmlcommon/` are clean — askpass is the model to copy, computing its
whole window height from `banner.height + body.implicitHeight`.

---

## 3. Colour

### 3.1 The wallpaper owns the palette; nothing picks a colour

**One accent, taken live from the active theme, applied to every zone — and
everything re-derives on a theme change without a restart.** [his] *"why does
the current theme only have the ram sticks tinted lightly with a yellow color?
all previously mentioned zones should be the accent color of the theme"* …
*"now make it so itll work with all current and future themes on the fly like
when the theme changes"*. That extends past the screen: the RGB in the case is
themed from the same palette.

`wal-set.sh` derives the palette and rewrites the block between the
`>>> wal palette` / `<<< wal palette` markers in the live
`~/.config/quickshell/Theme.qml`. **That file is the single palette source for
the whole desktop**: the panel reads it as a singleton, all six apps parse and
file-watch it (`PANEL_THEME` in every `main.py`), and the same script rewrites
Hyprland's border colours, the `plugin:hyprvtb:col.*` keys, kitty, the cursor
and OpenRGB. It is spliced **in place, same inode** — Quickshell watches by
inode, so a temp-and-rename would silently detach the watch — and it is the
**last** apply step, because writing it hot-reloads the whole QML tree.

**There are exactly zero hardcoded hex colours in the panel outside that
block.** The only raw colour expressions in 99 files are four black scrims and
`"transparent"`. Hold that line: if you are typing `#`, you are wrong.

**The palette is ONE HUE.** `home/srvs/wal-files/wal-extract.py` quantizes the
wallpaper to 16 clusters, picks the one maximising `s^1.5 * v^0.5 * count`
(vibrancy x frequency, so a black background cannot win), and then derives every
token from that single hue as an **HSV value ladder with saturation capped
inversely to value**:

```
BG        = 000000                       # hardcoded, never derived
BGALT     = (h, min(s,0.55), 0.07)
HIGHLIGHT = (h, min(s,0.60), 0.13)
BORDER    = (h, min(s,0.60), 0.22)
DIM       = (h, min(s,0.50), 0.33)
TEXTDIM   = (h, min(s,0.40), 0.60)
ACCENT    = (h, PASTEL,      max(v,0.90))    # PASTEL = min(s, 0.34)
TEXT      = ACCENT                            # body text IS the accent
OK/WARN/CRIT/INFO = same hue, 0.92 / 0.80 / 0.98 / 0.72
```

Three decisions are baked in there and should not be undone casually: the
**pastel cap** (`min(s, 0.34)` — "a bright surface with high saturation reads as
neon on the black panel"); dark structural tones keeping more chroma because low
value does not glow; and a **greyscale guard** (if the image's mean saturation
is under 0.15, clamp `s <= 0.12` — silver stays silver). Only `CRIT` gets extra
chroma, so an alarm can read against a monochrome desktop.

| name | role |
|---|---|
| `bg` | surface background — **pure black** |
| `bgAlt` | secondary/inset background, and the **unlit** colour (§3.4) |
| `border` | hairlines and frames |
| `accent` | active, focused, occupied, selected — **and body text** |
| `dim` | inactive, empty, unviewed |
| `text` | primary label |
| `textDim` | secondary label |
| `highlight` | selection background |
| `ok` / `warn` / `crit` / `info` | status ramp |

Plus two derived frame colours so an overlay surface reads as a window:
`windowBorder` = `accent` at `0xee` (matching Hyprland's `col.active_border`),
and `windowBorderInactive` = `rgba(595959aa)` — **static, not wal-derived**,
mirroring `col.inactive_border`.

Three settled palette decisions, all [code]:

- **Pastel, not fluorescent** (`3d1d80c`): saturation is capped on bright
  surfaces while value is lifted — "a soft pastel rather than neon on the black
  panel". Dark structural tones keep their chroma; low value doesn't glow.
- **Backgrounds are pure black**, not the near-black `bgAlt` (`e57e306`,
  `a316ad6`, `21caea4`) — so KDE/Qt apps, kitty and the panel are uniformly
  black. The OSD card was moved onto pure `bg` because "it was the one popup not
  on black".
- **Body text is the accent colour** — the same colour hyprvtb paints a focused
  window's title, so terminal, panel and Qt apps share one focus colour
  (`bef5518`, `603bfaa`). Rejected: the brighter `text` slot, which made
  titlebar text read red while terminal text read orange.

### 3.2 Two tiers: fills dim, indicators bright

[his] *"the line representing vol level changed colors to match the bars. it
should not have, it should be a different color so it stands out on top"* …
*"make the actual bars colors the same as the theme color used in the text of
the time played / time remaining part. so the actual bars will be a darker shade
than the peak bars. then do the same coloring for the panel volume bar"*.

Two things to take from that. **The bulk of an element takes the darker theme
shade and the indicator riding on it takes the brighter one**; and **colours are
borrowed by reference to an existing themed element** ("same as the artist
text"), never invented. Note he propagated the rule to the sibling widget in the
same breath, unprompted.

**Contrast is measured, not judged.** [code — `7628fed`] Because the wal palette
is monochromatic, *every* slot is a near-neighbour of accent (text 1.40:1, crit
1.49:1, ok 1.20:1). So **an indicator that must read against any wallpaper uses
a static colour that deliberately does not recolour with the palette** —
`windowBorderInactive` is the cited precedent.

### 3.3 State is a brightness ladder on one hue

[his] *"the program icons should actually show the states of every window…
full accent color for unrolled and focused. slightly dimmer color for unrolled
and unfocued, slightly dimmer than that for rolled up, and the current unfocused
color of the buttons will be the minimized indicator color"*

**Multiple states of one control are monotonic steps of accent brightness, not
different colours.** Where a state outranks another, say so explicitly: roll and
minimize outrank focus, because a rolled-up window can still hold the keyboard.

### 3.3.1 N series on one hue is a LADDER, and the key is never the colour

[code] The corollary of 3.1 for graphs: **a chart with N lines cannot hand out N
colours, because there is only ever one hue to give.** Two or three series get
away with borrowing from the status ramp (`crit` for the temperature riding over
`accent` for the load, on the cpu and gpu cards) — but that ramp is four slots
deep and every one of them is a near-neighbour of accent, so it does not scale
and it is not a palette.

So a set of *peers* — the `fan` card's one line per fan — is drawn as
**monotonic steps of accent brightness**, computed from the live palette
(`Qt.tint` toward `dim`), never as invented hues. It is 3.3's rule applied to
series instead of states.

**And the colour is never the only key**, which is what makes the degradation
safe: every line has a named row with its exact number in the tooltip, in the
same order as the ladder. The ladder stays legible to about five or six lines;
past that two steps look alike, and the widget is still readable because you can
count. Design for that, rather than for a hue rotation the palette cannot
express — a seventh series must degrade, not break.

### 3.4 Unlit is `bgAlt`, and unlit grids are dropped entirely

**An "off" segment or dot is drawn in `bgAlt`, not `dim`.** [code — recorded as
wrong *twice*] `dim` against `accent` has so little contrast that a 5x7 grid
reads as a solid block and every seven-segment digit reads as an 8.

And where there is no meaningful unlit state, **draw only the lit cells**:
[his] *"in the dotmatrix clock, remove the 'turned off' dots from view, only
active should be visable. and make those out of glyphs from the moreperfect
font."* Note both halves — lit-only, *and* built from the pixel font's own
glyphs rather than drawn primitives.

### 3.5 Say a state twice when the colour alone can be missed

[code] The battery reads `chg` / `ac` / `full` *and* goes `Theme.info` while
charging *and* prefixes the percentage with `+`; the panel's battery label flips
`bat` → `chg` because the green value colour alone "was easy to miss near full
charge". Charging outranks level in the ramp — 15% and climbing is not a
warning. He asked for it: *"make it so the battery graph text indicates charging
when needed as well"*.

---

## 4. Geometry — corners, borders, shadows

**Square corners.** [code] `decoration.rounding = 0` in Hyprland,
`windowRounding: 0` in the panel and all six apps, and Breeze was **patched from
source** (`Frame_FrameRadius 5 → 0`, `e5c0449`) because it has no runtime
setting. Nothing that reads as a *window or surface* is rounded.

**The two exceptions, and they are the only ones:** the panel's menus and
tooltips use `radius: 3` (`ProcMenu`, `TaskMenu`, `Tooltip`), and its text-entry
boxes use `radius: 2` (`Launcher`, `Lock`). **All six apps now have zero
`radius:` anywhere** — painter carried six until they were removed (§19.1), and
they were never a precedent. **Do not introduce a third rounding value.**

**Borders: 1px resting, 2px active.** [code] The single most-repeated idiom in
the panel, written out identically in six places and worth knowing by heart:

```qml
color:        active ? Theme.bgAlt   : "transparent"
border.width: active ? 2             : 1
border.color: active ? Theme.accent  : Theme.border
```

`"transparent"` is the resting fill throughout — **a fill appears in order to
mean focus.** Chips and toggles use a two-property variant that keeps the width
at 1 and only moves the colour.

**2px, on every edge.** [code/his] `general.border_size = 2`;
`windowBorderWidth: 2` in every `Theme.qml`; `VTB_PAD` and `VTB_CELL_GAP` = 2.
The desktop's own edge accents are 2px on **all four** sides — he added top and
bottom himself on one machine and then chased them onto the other (*"why did it
not show up here on top after pulling and rebuilding"*), and 1px was rejected
because a single physical pixel at the screen edge is invisible at scale 1.0
(`f7aceac` reverting `d35ee95`). Where the panel meets a maximized window, the
window border and the panel's accent stripe **coincide on the same 2px**
(`671150a`) rather than stacking into a double-width line.

**Shadows: one hard bottom-left drop shadow, 24px, constant alpha, never over a
window.** [his — a multi-session campaign] Four rules, each from a separate
report:

- *"overlapping shadows from different windows should not make the overlapping
  part darker as they currently do. it should stay the same opacity / alpha."*
  → one flat union layer, painted once per pixel (`ab5b58e`).
- *"the shadow (on both opening and unrolling) will be darker during its
  animation than when it is finished — causing this jarring kind of flash. its
  opacity should always be like how it is at rest."*
- *"shadows should never appear overtop unrolled windows/titlebars"* — and it
  must hold **from frame zero of the animation, not from its end**, and for
  **every** window below, not just the nearest. He had to report all three
  variants separately (`26fde39`, `0162c6d`).
- *"windows have a second sort of 'glow' shadow around them, very small and
  right on the window border. it should not have this."* → Hyprland's native
  soft shadow is `enabled = false`.

Rejected: 8px ("an overhang too thin to notice"), per-window shadow draws (they
stacked to ~0.84 alpha where they overlapped), and the roll animation's shadow
as a separate rect.

**Opacity is binary.** [code] There are no translucent panels and no glass. The
complete inventory is `0`/`1` toggles, `0.4` for disabled, `0.45`/`0.7` for an
icon knocked back, and four black scrims. The only alpha *in* the palette is
derived: `windowBorder` at `0xee`, `windowBorderInactive` at `0xaa`.

### 4.1 The spacing scale

`Theme.gap` = **8** is the layout unit — 55 uses, second only to `Theme.accent`.
It governs bar cluster spacing, popup window margins, the notification stack,
the dock header flow and the dock grid gutter. Derived forms are `gap*2` and
`gap*3`.

**Inside a widget the scale is 1 / 2 / 4 / 6 / 8 / 10 / 12**, with 6 and 8
dominating. It is not named anywhere; use those values and no others. Two
conventions that *are* honoured and should be:

- **`pad: 10` is a content component's outer inset** (`MetricChart`,
  `CalendarContent`, `WeatherContent`, `ClockContent`, `DiskContent`,
  `MediaContent`), and inner width is `width - pad*2` — never a hardcoded
  `width - 24`.
- **A text-only row is `Theme.fontSize` tall** (§2.1). Menu rows are the text's
  own line box with no padding: *"kitty-exact menu row … vs the old +12 that
  left dead space above/below each label"*.

Cell sizes: `Theme.cell` 40 (tray), `Theme.wsCell` 32 (task cells, runner
button), `Theme.barWidth` 48 (the *classic* bar width only — read
`ViewMode.barWidth` for "how much screen does the panel take"). Icon sizes are
derived from a cell, never literal: tray `cell - 18`, task icon `wsCell - 12`,
runner glyph `wsCell - 18`.

**Hit targets are expanded with negative anchor margins** (−2 to −5), never by
growing the drawn item — see §5.3.

Window layout constants: `gaps_in 5`, `gaps_out 35`, `border_size 2`,
`rounding 0`, `active_opacity = inactive_opacity = 1.0`.

---

## 5. Density and layout

### 5.1 Zero-gap, edge-to-edge

[his, his second-strongest rule after kitty] Four separate statements, three
surfaces:

> *"the album cover view should only display the title, artist, and year text on
> hover over and only inside the cover image itself so that all the covers can
> have 0px space between them"*
>
> *"make the spacing between the bars 0"* … *"it seems like you could fit
> another bar (or two?) between the two left and right bars on the panel to make
> the space between them zero like we just did for the full spectrum"*
>
> *"make it so on the now playing screen, the cover art extends to the very
> edges of the window meeting the outline instead of having black margins
> around it"*

**Tiled elements butt together at 0px; imagery bleeds to the window outline with
no letterboxing (square art crops rather than pillarboxes); labels move *inside*
the artwork on hover rather than claiming a strip of their own.** The frame is
the window's own outline — do not draw a second one inside it.

Implementation note [code — `5b09a8c`, `478825e`]: **position gapless bars from
the shared edge**, `round(w*i/n) .. round(w*(i+1)/n)`, so one bar's right edge
*is* the next one's left edge. `spacing: 0` on a `Row` is not the same thing —
fractional widths round independently and leave subpixel seams. For the same
reason a border wraps both VU channels rather than each: per-channel borders put
two 1px lines back to back down the middle, which is a 2px seam, i.e. exactly
the gap being closed.

### 5.2 Dead space is a defect

[his] *"the clock widget itself should be sized so that the empty portion below
the calendar disappears… the blank space below it should also be removed"*;
*"you failed to remove the weird empty middle section in the now playing page"*;
*"if there's enough room for more of the dir name to display, then filer should
take it. it currently leaves all that space on the right empty"*.

- **Widgets grow into the tile they are handed.** [code] Reclaiming slack is a
  property of the widgets, not of hand-tuned row spans; each keeps a `natural*`
  constant that `implicitHeight` is built from (deriving it from `height` is a
  binding loop). `qs ipc call live tiles` exists so this is measurable rather
  than eyeballed.
- **Text columns expand to consume available width before eliding.** Leftover
  space on the right is a bug.
- **Two lines become one, laid out horizontally**, where they can: *"for every
  graph that has two rows of text (cpu, gpu, mem, ...) the text in the lower row
  should just be potitioned to the left of the text on the top row,
  consolidating the two lines"*.
- **Nothing below the fold.** [his] *"all of these widgets should only take up
  enough space for a single 'page' so the user does not have to scroll down to
  view more widgets"*. The dock grid derives its row height from the panel
  height and does not scroll. The cost is real and accepted: a new widget takes
  rows from the others, and if none can spare them, it does not fit.

### 5.3 The floor: an interactive target never touches its neighbour

[his — the necessary counterweight to §5.1] *"the toggle to slide back up the
queue of the media player widget in the pannel is too high up and basically
touching the last item shown in the queue. hard to click on"*.

Measured, it was literal: the last row's bottom edge *was* the handle's top
edge, `gap = 0`, so hitting "play that track" instead was one pixel of overshoot
away. The fix (`7b0db97`) is the pattern: padding above and below, the control
grown 11→14px, and **the hit target made bigger than the strip it draws** (19px
vs 11px) with no extra chrome, stopping short of the gap so it cannot collide
with the row above. The cost was stated openly rather than discovered — the list
went 98px → 87px.

**A module's hit band spans the full bar width; only its content is centred.**
[his — `9af54aa`, `43bd537`] "so you don't have to land on the text itself". The
VU was a ~14px centred strip you had to hit exactly.

### 5.4 Reserve the space, drop the label

[his] *"remove the top label"*; *"the top text is just going to be one line. the
title will be on the left and the artist will be on the right. remove the em -
dash and when there's nothing playing, just reserve empty space for the single
line top text"*.

**Widget titles and headers come off — the content identifies itself — but the
slot stays allocated so nothing reflows when data is absent.** Paired values
split to opposite edges of one line rather than being joined by a separator
glyph. Empty means empty, not a placeholder.

**The distinction that resolves the apparent contradiction with §5.2:
transient absence RESERVES; permanent absence COLLAPSES.** Nothing playing →
the media line keeps its height and goes blank. No lyrics for this track ever →
*"if no lyrics are shown, then just hide its column"*.

**The lyrics box is one presentation, drawn in two trees.** [his] *"when a track
has lyrics, the right side of the player widget queue becomes like the lyrics box
of the player program"* — so the panel's media queue drawer carries a parallel
implementation of `apps/player/qml/LyricsView.qml`: same right-hand column, same
1px `Theme.border` divider, centred lines, the current one in `Theme.text` and
the rest in `Theme.textDim`, click a line to seek, and the whole column
collapsing to zero width on a track with no words. It is a copy because the two
trees cannot share a component (Quickshell QML vs plain Qt, and the panel cannot
import `apps/qmlcommon/`) — the same standing arrangement as `PixelText` and the
`Kinetic*` types. **Retune one and retune the other.**

It costs the ARTIST column, which the box sits on top of, and the durations move
left to sit against the divider — the queue keeps "what is next" and "how long",
and gives up the one field the line above already states for the track playing.
Note the shape of that trade: a column is surrendered to a column, not squeezed
beside it, and **nothing about the widget's height changes** — the box lives
inside the drawer the dock grid has already handed over (§18), so the weather
tile below it does not move.

### 5.5 Position is a property of the element, not of the view

[his] *"the cover section with the text underneith should be on the right side
of the play instead of the left — **on both** the individual album view and the
now playing view"*. When an element's position is fixed in one view, the same
element takes the same position in every other view.

Related [code]: desktop widgets tile by a **fixed `tileRank`, not
pin-insertion order**, "so the media widget always lands between the disk and
clock regardless of when it was pinned".

### 5.6 Layouts must survive the small screen

[his] *"in player, on air (NOT ON TOP nixosbox) the now playing page should be
able to be shrunk a bit more and the cover displayed be sized appropriately.
right now its like its sized to fix on tops larger screen"*. player runs at
~480x826 on book. No layout may have a minimum sized for the desktop monitor.

---

## 6. Motion

### 6.1 Reload in place — the most-repeated rule in the corpus

[his — 7 turns across 6 sessions, and still not fully satisfied]

> *"when an agent needs to do a hot reload, or the user changes the theme,
> basically everything works as it should except the desktop widgets. everything
> else appears as if things simply reset 'in place' i.e. nothing jitters, moves,
> changes… but the widgets do not follow this same 'appear as if state was
> changed in place' rule. they move around and meander to their original
> positions instead. i want it to even go to the level of the cpu gpu eth etc
> graph information seems to have switched in place. the spectrums as well!"*
>
> *"they should just appear tho transition into their new version, not have this
> weird jump where they go through their animations again"*
>
> *"when you hotreload, rolled up windows will snap to being unrolled after.
> that should not happen"*
>
> *"reloading the quickshell config (and perhaps hot reloading in general?)
> still flashes the wallpaper when it should not, it should be 'in place' as
> everything else"*

**A config reload, theme change, wallpaper change or agent hot-reload must be
visually undetectable.** No disappear/reappear, no re-running entrance
animations, no jitter, no wallpaper flash, no panel movement, no rolled-up
window snapping open — and even *data* (graph history, spectrum levels) carries
over. **The maintenance mechanism must never be visible to the user.**

What that costs you, mechanically:

- **Every binding in a fresh tree is first evaluated against the SHIPPED
  DEFAULTS**, so the correction to the real value gets played as an animation:
  the panel grew out of the screen edge over 200ms and the wallpaper slid across
  the screen over 260ms on every theme change. `ViewMode.settling` is true for
  the first 400ms of every tree and everything animating a persisted geometry
  value gates its `Behavior` on it. **Add a `Behavior` on anything that follows
  a persisted value and you must gate it too**, or you have re-added the glitch
  for that one widget.
- **NOTHING ON SCREEN MAY LOAD ASYNCHRONOUSLY.** The first paint of a tree is
  synchronous — only the first paint, never a cross-fade. Twice in one day the
  same shape produced the same report: async image decode showed flat
  `Theme.bg` full-screen for ~100ms on every theme change (`efccc34`), and
  `DockTile`'s asynchronous `Loader` put every dock widget **82-95 ms after**
  the frame that painted the panel (`79e9dea`) — a panel of empty frames, which
  is what "the widgets all flash black" meant. *Async is the right default for
  everything else*, and it stays: a cross-fade must stay asynchronous, because
  the outgoing frame is still on screen. **The rule is about the FIRST frame of
  a tree** — anything that has to be in it loads blocking, and `loadNow()` is
  the idiom (`SettingsStore`, `Wall`, `WallpaperImage`).
- **A one-shot handler cannot be gated; it must LOAD.** `SettingsStore.loadNow()`
  / `Wall.loadNow()` first in any `Component.onCompleted` that branches on a
  persisted value.

### 6.2 One motion vocabulary — and the window roll is the reference

[his, stated as a design-language rule in his own words]

> *"make the sliding animations for the queue of the media player widget to
> match the sliding animation speed / timing of the window roll in and out ---
> !! this is another thing that should always happen when we do a new feature or
> program etc design language"*

**Every sliding/revealing animation on this desktop runs at the same speed and
timing, and the reference is hyprvtb's window roll in/out.** A new drawer,
panel, popup, tooltip or transport reveal does not get to pick its own duration
or curve — it takes the desktop's.

Note the shape of the request: he had to ask for it **after the fact**, for one
widget, having already asked the same kind of thing about split-button glyphs
earlier the same day. That is precisely the class of thing this document exists
to stop him having to say. **When you add anything that moves, this section is
the answer — do not re-decide it.**

**The number is 260 ms on `Easing.OutCubic`, and it is the roll's own.** Not a
preference — measured out of the reference itself: the roll runs over
`slide_duration_ms` (260) in two beats, the drawer slide over the first
`roll_slide_frac` (55%) on an ease-out cubic and the set-down over the rest on
an ease-in-out. `slideEasing` matches the *leading* beat, the one that carries
the visible travel. The residual difference is the last ~45%: the roll eases
back *in* as the bar sets down, and a QML `NumberAnimation` does not. Nothing in
the panel needs that second beat, because it exists because the bar changes
DIRECTION and no panel drawer does.

**There is exactly one home for it, and it is a config key.** Until hyprvtb 2.89
the roll's timing was a compiled-in `static constexpr` with nothing to read, so
every other codebase hand-copied the number out of a C++ comment — which is how
the panel spent its life at 220 against a roll at 260. It is now
**`plugin:hyprvtb:slide_duration_ms`** (and `roll_slide_frac`), set in
`hyprland.lua`, and the plugin publishes the resolved values on every config
reload so the other two runtimes *read* it instead of copying it:

| reader | mechanism | liveness |
|---|---|---|
| hyprvtb itself | `Cfg::slideDurationMs()` | live, every frame |
| the panel | `ViewMode.slideMs`, a `FileView` on `~/.local/state/hyprvtb/motion.json` with `watchChanges` | live — `hyprctl reload` reaches a running panel |
| the six apps | `qmlcommon/Motion.qml`, a `Loader` on the generated `~/.local/state/hyprvtb/DeskMotion.qml` | at app start (these apps have no hot reload at all) |

So retuning the whole desktop's motion is one number in `hyprland.lua` plus
`hyprctl reload`. Each reader keeps 260 as a **fallback**, because the panel and
the apps must draw a correct desktop with the plugin disabled or quarantined —
those literals have to stay equal to the key's default in `hyprvtb/main.cpp`.

> Two files rather than one because the two readers cannot read the same thing.
> Quickshell has `FileView`; plain Qt QML has no file reader at all —
> `XMLHttpRequest` refuses a `file://` URL unless `QML_XHR_ALLOW_FILE_READ` is
> exported into the app, which is a blanket local-file-read permission granted
> to, among others, a web browser. A `Loader` on an absolute `file:` URL needs no
> permission and reports `Loader.Error` for a missing file, which is exactly the
> fallback signal wanted. Both were measured offscreen before this was written.

**And every duration goes through a scaling function** — `ViewMode.ms()` in the
panel, `Motion.ms()` in the apps. That is what finally made `reduceMotion` and
`animSpeed` real: both settings had existed in `SettingsStore` and in the
Settings window since the day they shipped and drove **nothing**, because every
`Behavior` in the tree carried its own literal. `reduceMotion` returns 0, which
a `NumberAnimation` treats as an immediate assignment — the desktop still
changes state, it just stops travelling to get there.

> **Both settings reach the apps through `DeskStyle`** (`apps/pylib/deskstyle.py`),
> the same context property that already carries `fontFamily`/`fontSize` from the
> panel's own `settings.json`, watching the file *and* its directory because
> `SettingsStore` writes atomically. The validation is deliberately the panel's
> and not the slider's — any finite `animSpeed > 0`, falling back to 1.0 — since
> a value outside the slider's 0.5-2.0 that the panel honoured and the apps
> clamped would be two speeds on one desktop, which is the thing this section
> exists to prevent. Measured offscreen against the real `Motion.qml`:
> `animSpeed` 2.0 turns the 260 ms slide into 520 and the 120 ms fade into 240,
> 0.5 into 130 and 60, `reduceMotion` collapses both to 0 — and a junk or
> deleted `settings.json` holds the last good values rather than blanking them.

**So: never write a duration literal into a widget.** `ViewMode.ms(ViewMode.slideMs)`
/ `motion.ms(motion.slideMs)`, and `ViewMode.slideEasing` / `motion.slideEasing`.
A literal is not merely untidy now; it is a widget that opts out of the user's
own settings and out of the compositor's key at the same time.

#### 6.2.1 The vocabulary, and what is deliberately not in it

**A reveal, a slide or a card movement is `slideMs` (260 ms) on `OutCubic`
unless there is a stated reason otherwise**, and the reason belongs in a comment
next to the number. [code — 25 of 30 easing declarations in the panel and apps
are `OutCubic`]

> **How this section used to read, and why the history stays.** It ratified
> **220 ms** as the house slide, on the evidence that 220 was the most common
> duration in the tree by a factor of four and was deliberately the same number
> in three codebases — `SlidePopup.qml`'s card slide, surfer's page tooltips
> commented as matching it, and `hyprvtb`'s `VTB_TT_SLIDE_MS = 220.f;
> // matches SlidePopup's 220ms card slide`. That reasoning was sound and its
> conclusion was still wrong: it counted call sites instead of asking what the
> rule above actually names. **The user overrode it explicitly** — *"make the
> sliding animations ... match the sliding animation speed / timing of the
> window roll in and out"* — and the roll was 260 the whole time. The three
> codebases had converged on each other while all three drifted from the
> reference. Left here because the failure mode is worth keeping: a majority
> vote among call sites is not a design decision, and the next audit will find
> the same tempting evidence.

| | |
|---|---|
| `hyprvtb/vtbDeco.cpp` | the roll — `Cfg::slideDurationSec()` / `Cfg::rollSlideFrac()`, the reference |
| `hyprvtb/vtbDeco.cpp` | the titlebar tooltip — the same key, no second number |
| `home/prog/quickshell-files/` | `ViewMode.ms(ViewMode.slideMs)` / `ViewMode.slideEasing` |
| `apps/*/qml/` | `motion.ms(motion.slideMs)` / `motion.slideEasing`, from `qmlcommon/Motion.qml` |
| `hyprland.lua` | `workspaces` at speed 2.2 on a hand-fitted `easeOutCubic` bezier, whose comment says it exists to be *"identical to the Quickshell workspace-outline slide … so the windows and the panel indicator move as one"* |

That last one is the principle in its clearest form: **a compositor bezier was
hand-fitted to Qt's easing curve specifically so two different renderers would
agree.** Hold that line.

**The deliberate non-participants.** Every one of these is a number with a
comment saying why, not an oversight — do not "converge" them:

| | | |
|---|---|---|
| `shell.qml` bar width settle | 200 ms | the tail of a **gesture**, not a reveal between rest states — §6.4 governs it, and it animates at all only under protest |
| `SetToggle.qml` knob | 90 ms | a ~14px knob inside the control you just clicked: press feedback, which belongs with the pointer |
| `vtbDeco.cpp` `VTB_FLASH_MS` | 220 ms | the compositor-side sibling of that knob — a clicked cell's activation flash. It now shares 220 with nothing, which is the point |
| crossfades, hover, scrollbars | 140 / 120 / 160 ms | opacity, with no travel to read. They take the house **curve** and go through `ms()`, but not the slide's duration |
| `WallpaperImage.qml` | 260 ms **InOutQuad** | a cross-fade between two full-screen pictures. An ease-out dumps most of the change into the first third, which reads as the old wallpaper being snatched away; the duration is the desktop's, the curve is symmetric on purpose |
| `Lock.qml` unlock fade | 300 ms, a **literal** | releasing the session lock is a side effect of this animation finishing. Through `ms()` it would be 0 under `reduceMotion`, and a zero-length animation need never report a running→stopped edge — the fade would "finish" with nobody left to unlock the screen. The failure mode is the user locked out of their own session |
| `VuMeter` / spectrum | 25 ms, no easing | already-smoothed 60fps data; a `Behavior` here is a second low-pass re-adding the lag cava was told to drop (§6.9) |

**Things slide OUT of the edge they belong to; they do not fade in from
nowhere.** [his] *"tooltips should slide out (like the surfer ones) and not
instantly either"*. The canonical form — implemented separately by the panel,
surfer and hyprvtb — is **a clipped chip growing from a FIXED far edge**: the
container is full size throughout and the *clip* grows. hyprvtb's tooltip was
reversed in 2.27 specifically to do this, *"like the quickshell widgets emerge
from the screen edge"*, and the fade was dropped in favour of a pure slide. A
drawer slides out **from its own button, toward it** (`fc73fed`).

**Do not animate the popup's own width** — that is a surface resize per frame,
a compositor configure roundtrip behind every step of the animation it is
supposed to be. And in QML the idiom is `Behavior on x` driven by a boolean,
**never** a `Popup` `enter`/`exit` `Transition`: a Transition and a permanent
`x` binding on the same property fight every frame, which is why filer's first
tooltip did not un-slide.

Other established durations — reuse rather than re-pick: **120ms** scrollbar
opacity fade, **0.16s** the hyprvtb lone-bar fade, **90ms** the unroll
reveal-hold. The widget fan and the delay before a replacing popup slides in
(§7.3) are both one slide's worth and take `slideMs` itself.

**A timer that guards an animation is derived from it, never written out.** Five
`Timer`s in the panel exist only to outlast a slide — unmapping a layer surface
after the card has travelled off it, holding a `_closing` flag through the
animation it gates. They were hand-maintained 260ms literals sitting against a
220ms slide, i.e. right by accident; converging the slide to 260 would have
landed every one of them **on the animation's last frame**, and at any
`animScale` other than 1 they were already firing before the thing they guard
had finished. The form is `ViewMode.ms(ViewMode.slideMs) + 20` — the margin is a
fixed frame and must NOT scale, or `reduceMotion` leaves no margin at all.

### 6.3 Nothing bounces, overshoots or settles

[his — six turns across five sessions; **"jarring" is his word for the whole
failure class**]

> *"after a window completes its opening animation it does a sort of almost like
> it gets a hair smaller for like half a second? … its jarring."*
>
> *"when moving the panel edge to the right and then releasing, the panel edge
> sort of skips to the left and then back to its position to the right. this is
> jarring."*
>
> *"sometimes when the user clicks to a new position on the bar, the indication
> horizontal bar and progress bar will jump back and forth a few times before
> settling"*

**An animation ends exactly where it is going, on the first try.**

**An animation chasing a target that is ITSELF animating is a bug**, not
smoothing: it retargets every frame and permanently trails (`30e6eab` — the
cover art ballooned 111→164px and snapped back to 60 while the queue slid).
Note the fix that was *tried first and does not work*: gating the `Behavior` on
`enabled:` off the same flag both bindings hang from — the height is written
before `enabled` is re-evaluated. Use a plain property seeded in
`Component.onCompleted`, held for one animation on the way down.

### 6.4 A direct-manipulation drag has zero easing

[his, stated three times in one session]

> *"the wallpaper edge, the outline border, and the hover over indicator should
> track the mouse exactly. not trailing behind."*
>
> *"instead of having the wallpaper follow the mouse, wait for the user to
> unclick and then gracefully move the wallpaper to that position. also clicking
> and depressing on the handle cause the panel to jump — jumps to the right when
> clicked and to the left when depressed"*

**Everything under the cursor tracks it 1:1 — no smoothing, no lag, no jump on
press or release. Easing is reserved for things that move AFTER the user lets
go.** He derived the exception himself: an expensive thing (the wallpaper
re-crop) glides to its target on release; the grabbed edge tracks exactly.

Three corollaries, all [code] and all learned the hard way:

- **Nothing that must track the pointer may be a layer-surface SIZE.** A
  layer-surface resize is a configure/ack roundtrip, so any surface whose width
  follows the cursor is a frame or more behind it. Put the moving edge in an
  **item binding inside a surface that does not resize**.
- **Never quantize a live drag.** Quantizing to the 8px grid made the edge
  advance in hops; its "sole remaining effect was jumping the panel up to 4px
  from where you released", so it was dropped entirely.
- **Never re-zone during a drag** — rewriting `exclusiveZone` per pointer event
  makes the compositor re-run the layout in the frame the resize is landing in.

### 6.5 Scope: only the thing you touched may move

[his] *"when opening and closing the queue in the media widget of the large bar,
the graphs, processes, weather calendar and clock widgets all flash black. they
should not do this. the queue should just smoothly slide down while the weather
widget smoothly condences."* And: *"when clicking the queue arrow, first the
album art expands to fill the space then it makes way for the queue"*.

**A disclosure animates only itself and its designated neighbour. Unrelated
widgets never re-render, never flash, never resize. And the transition is
monotonic** — no intermediate state where a sibling expands into space it is
about to give up.

The black-flash cause is a pattern that will recur: **a JS-array model that
re-evaluates is replaced wholesale, and the `Repeater` answers by destroying and
re-creating every delegate.** Never make a Repeater's model depend on anything
that changes at runtime; give the tile that has to move a per-tile *delta* in
its own bindings instead.

### 6.6 Z-order changes at the END of the motion

[his] *"when rolling up windows, the focused window rolling up immedietly moves
to behind all other windows. it should not, it should stay ontop until the slide
in animation is complete"*. The thing the user is looking at stays the thing on
top until it is done moving.

### 6.7 A composite element fades in as ONE object

[his — the most detailed chrome correction in the corpus]

> *"the accent color on the button labels are shown at fade in (on window
> creation) but the titlebars outline is not. the titlebars outline only appears
> once the titlebar has finished its fading in animation. then, at the same
> time, the already accent colored button labels flash to black and then back to
> the accent color quickly. this is incredible jarring. the accent color on the
> button labels AND the outline should both appear at the same time on fade in
> and should not flash to black or anything"*

**Outline, labels and colour become visible on the same frame. No sub-element
leads or lags, and nothing transits through an unstyled state on its way to its
final colour.** Generalised: **an element never shows a half-built state.** In
hyprvtb this meant tying the bar's tint to `rollSlideT` (the slide) rather than
to the set-down beat, and extending the border crossfade to wrap the titlebar
(`638fbd1`, `845e12c`).

### 6.8 No default animations, and no login animation

**Every window uses the desktop's own open/close animation** [his] — *"all their
start animations were simple default fade in's not our custom one"*. A default
fade-in is a bug, including for the bespoke apps.

**No entrance animation at login** [code] — `monitorAdded` is explicitly
disabled with the comment *"the desktop should just BE there"*.

**No transient window may flash into view as a side effect of something
unrelated** [his] — *"i went frame by frame myself and saw that its the
KEYBINDINGS WINDOW haha. that should never be seen when resizing the panel."*

### 6.9 Physics-driven indicators use physics, not easing

[code — `5b09a8c`] The spectrum's peak markers use a **gravity model, not a
decay**: "the velocity term is what makes a peak read as falling rather than
fading". And **the marker deliberately has no `Behavior`** — the fall is already
interpolated frame by frame, and animating it would drag the marker behind the
peak it exists to pin. Constants were checked against 10s of captured playback.

Related [code — `f3c6040`]: a QML `Behavior` over already-smoothed 60fps data is
"a second low-pass … re-adding the lag cava had just been told to drop". It went
60ms → 25ms.

### 6.10 The slow-motion knob `[panel]`

[code — `52a7989`] Every duration a view-mode change touches goes through
`ViewMode.ms()`, scaled by a runtime `slowmo`, because "there is a glitch in the
settle … too fast to see, let alone diagnose". It is **deliberately not
persisted and not a settings key**, so a reload always restores 1x and it cannot
be left on by accident. He asked for exactly this: *"can you slow the animations
down enough to where i can record it"*.

---

## 7. Menus, popups and dialogs

**A popup that maps at ZERO SIZE kills the entire panel.** [code — the most
destructive UI bug this repo has recorded] `xdg_positioner.set_size` rejects a
non-positive dimension with a Wayland *protocol error*, which disconnects the
client: bar, wallpaper and every popup exit together, on the first click that
opens the menu. The same shape bit surfer more mildly first — a right-click menu
"smaller than the cursor". Three rules:

- **Compute a popup's implicit size only from things that do not follow the
  popup's size**, with `Math.max(1, …)` as the floor "so the next mistake of
  this shape is an ugly menu and not a dead desktop". A `Column` that
  `anchors.fill`s its parent takes its implicit size from its children's
  laid-out widths — so a popup sized from that Column is defined in terms of
  itself and resolves to 0.
- **Measure on your own flag, never on `visible`.** `Item.visible` is
  *effective* visibility and is false inside an unmapped window — and a popup is
  unmapped whenever it is closed. Measuring over `visible` gives a correct size
  on the first open and 0x0 on every one after: a menu that works once per panel
  lifetime and then silently refuses forever.
- **Refuse to open on a degenerate measurement**, with a warning, rather than
  mapping it.

Verify off-screen in a `FloatingWindow` under `tools/sandbox.sh`, and **cycle
close→open at least twice** — the second open is the case above.

### 7.1 Everything selectable is right-clickable

[his — stated on four different surfaces in four sessions]

> *"please add a function right click menu with options of a typical
> filemanager."* / *"the right click mennu should have many of the functions of
> a normal right click browser menu"* / *"the user should be able to right click
> on an album cover and have a menu come up to play, add to queue, search by
> artist"* / *"the user should be able to right click on processes in the system
> monitor and have a menu come up with different appropriate actions"*

**This is a default, not a request.** A new list, grid or table ships with a
context menu carrying the actions a user of that *category* of app would expect.

### 7.2 Menus are ours

**Themed, `PixelText`, our own component — never Chromium's, never Qt's native
styling.** [code — `8c76d7a`, `e7db0e9`, `57cd299`] `CtxMenu.qml` is
deliberately generic so filer, player and the desktop reuse it verbatim.
Menu-item backgrounds are sized from the text's real metrics — *"half of the
delete text gets cut off due to the background being too short"*.

**No dialog borrows another toolkit's theme** [his]: *"the askpass just popped up
and it still looked like the old light theme"*, and the fix was to stop
restyling ksshaskpass and write our own — "restyling someone else's dialog was
never going to make the two hosts agree".

**The menu spec, identical in the panel and in filer/player/surfer** [code]:
box `Theme.bgAlt` + 1px `Theme.border` + `radius: 3`; row height is the text's
own line box; `implicitWidth: text + 24` with a 10-12px left margin; **hover
fills `Theme.highlight` — one step LIGHTER than the menu**, the same selection
fill the task table's rows take, per §3.3's brightness ladder; disabled text
`Theme.inactive`; separator is a 1px `Theme.border` line centred in a 5-7px row;
`PointingHandCursor`; dismissal on select, outside click, Escape, or a 400ms
leave timer. Item shape is `{label, enabled?, separator?, trigger?}`.

**This paragraph said "hover fills `Theme.bg` — darker than the menu, inverted
from the usual hover-lightens" until 2026-07-27, and it was wrong.** It had been
promoted from `TaskMenu.qml` (`155f6b4`), the first menu written here, whose
hover was never a decision — the same file also painted `Force Quit` in
`Theme.accent` and Title-Cased its labels, and both of those were plainly
accidents. Nothing anywhere states a reason for menus to invert; the rest of the
desktop hovers *up* the ladder without exception (eight fills in the panel alone
— `BrowserButton`, `SetSelect`, `SetPgWidgets`, `MediaContent`, and the task
table's own rows), `highlight`'s own comment reads "selection bg", and the three
apps' menus — the majority, and independently written from surfer's — already
did that. So the rule moved to where the desktop already was and the panel's two
menus came with it, rather than the document's accident being copied into a
sixth surface.

**Ordering is a safety property, and it is the same in every menu:** the primary
or read-only actions first (filer opens with `open`; the process menu opens with
`filter by name` / `copy pid`), state changes next, and **anything destructive
LAST, behind a separator** (§10.3). The pointer's landing spot must never be an
entry that cannot be undone — least of all over a list that re-sorts under it.

**Menu labels are lowercase**, like every other string this desktop authors.
(surfer's page menu is Sentence case because it mirrors Chromium's own wording;
that one is unruled — §19.2 item 2.)

**Modal dialog spec, identical in filer and surfer** [code]:
`Qt.rgba(0,0,0,0.5)` scrim, click-outside cancels and an inner `MouseArea`
swallows; box `Theme.bg` + `Theme.windowBorder` at `Theme.windowBorderWidth`;
`Column margins: 12`, `spacing: 8-10`; right-aligned button row `spacing: 6-8`;
text field `height: 24`, `bgAlt` fill, 1px `Theme.accent` border, `margins: 4`.

### 7.3 One popup at a time, sequentially

[code — `babb941`] Claiming while another is open dismisses it and **delays the
new card until the old has slid fully away** (260ms). Popups **size to content**
— no empty tails (`8d06300`); the calendar adapts to 5- vs 6-row months.

**If an endpoint can move while a popup is SHUT, its `Behavior` must be gated**
[code — `f780f70`], or the closed card animates itself into view. An ungated
`Behavior on x` made a shut cheatsheet glide 220ms across the desktop every time
the panel was resized.

### 7.4 The inner titlebar is the app's navigation bar

[his] *"remove the close button in the inner titlebar and instead have the
albums, playlists, now playing, and sort buttons displayed there. there should
also be a search button which when clicked a search bar will slide out from the
button"*, and — explicitly cross-app — *"like how other programs have special
buttons in that location"*.

**Page switches and app-level actions live in the titlebar, not in an in-content
toolbar. Secondary UI (settings, search) slides out from the button that owns
it** rather than opening a separate window or modal. The window itself is
content: *"In-window header row removed; views get the full window. App close
button dropped — the outer titlebar's [x] does that"* (`1eb7ede`).

### 7.5 Modals

- **A modal centres, every time** — it never inherits remembered geometry.
  (`askpass` is excluded from hyprvtb's geometry memory in all three directions.)
- **A modal dim covers everything, panel included** [his] — *"the modal read as
  half-applied"*. The bar paints its own scrim at Hyprland's own
  `decoration:dim_strength`, because `dim_around` is drawn in the window pass
  and the bar is a layer surface above it.
- **A privilege prompt states the caller's reason and never invents one.**
  [his] `[askpass]`
  Unset reads "NO REASON GIVEN", because "a prompt that fabricates a
  justification for its own privilege request is worse than one that admits
  ignorance". Untrusted strings are sanitized (C0/C1 stripped, newlines
  flattened, length clamped) and **the reason sits in its own captioned box so
  it can never read as the dialog's own voice**.
- **The privilege prompt has NO titlebar at all — the window and nothing else.**
  [his] `[askpass]` *"the visual sudo prompt shouldnt have any titlebar at all,
  just the window."* This is §1's honesty rule read backwards: a control that is
  drawn is a control that works, so a control that cannot work is not drawn.
  Every cell the bar offers is one this modal must not have — it is fixed-size
  (min == max), centred and pinned by its window rule, never remembered, and
  rolled up or minimized it would leave a `sudo` blocked on a window you can no
  longer see. What was left was an [x] that duplicated the dialog's own Cancel
  (both: exit 1, empty stdout) at the price of a bar's width of reserved
  chrome. So hyprvtb attaches no titlebar to `vista-askpass` at all —
  `vtbNeverDecorates()`, ≥2.94, the same treatment the scratchpad has always
  had. **§4's hard drop shadow stays**: it is the window's, not its chrome, and
  it is what says "this floats above the dimmed desktop". The plugin hands the
  window the keyboard explicitly in place of the open reveal's focus grant —
  a password prompt that opens unfocused is the one regression this must never
  ship.

---

## 8. Tooltips

**A dwell, then a 220ms clipped slide out of a fixed edge, in theme colours and
`PixelText` — never a native Qt tooltip.** [his] *"add tool tips (properly
styled formatted themed) for all the buttons"*; *"tooltips should slide out
(like the surfer ones) and not instantly either"*.

- **Every button gets one, and any graph whose encoding is not self-evident gets
  one.** [his] *"what does the line represent? cant tell."* A four-character
  metric label cannot say what it measures; the tooltip is where "psi" or "res"
  explains itself.
- **Drive them by a `show` (hover) flag, never by `visible`.** [code] The
  tooltip owns its own visibility; assigning `visible` from a call site
  overrides the animation's binding and it is back to blinking in and out.
- **They animate even on a motionless cursor.** hyprvtb's dwell rides the
  mouse-move hook plus a 150ms heartbeat; do not implement one that needs a
  twitch.
- **Suppressed on unfocused windows** [code — `737dce7`] — "the cursor is
  usually just passing over it to click-focus".

**The spec** [code — `Tooltip.qml`]: chip is `Theme.bgAlt` + 1px `Theme.border`
+ `radius: 3`, `implicitWidth: label + 16`, `implicitHeight: label + 10`. The
reveal is a **clip growing leftward from a fixed right edge**; the window never
resizes. Retraction is immediate. Recompute the anchor on every open —
`mapToItem` in a plain binding captures ancestor positions **once**, at
creation.

**Known divergence:** the dwell is **350ms** in the panel and **450ms** in
hyprvtb. See [Open questions](#open-questions).

### 8.1 Toasts, OSD and status text — the exact specs `[panel]`

- **Notification card**: width 300, `implicitHeight: max(Theme.cell, content +
  20)`, `radius: 0`, `Theme.bgAlt` fill, **2px border in the urgency tint plus a
  3px left urgency strip**. Three lines — app name in the tint, summary in
  `Theme.text` (max 2 lines), body in `Theme.textDim` (max 4). Tint: critical →
  `crit`, urgency 0 → `info`, else `accent`. Fade in 160ms OutCubic; removal is
  instant. The stack spaces by `Theme.gap` and enters from ±48px over 180ms.
- **OSD**: 40x184, docked bottom-right at `Theme.gap`, card `Theme.bg` with a
  **2px `Theme.accent`** border — pure black like the runner, power menu and
  cheatsheet, because "this was the one popup still on the tinted bgAlt".
  Three-letter labels (`bri` / `gma` / `vol`), tinted by kind. Negative
  brightness **hangs its fill down from the top**, so the range below hardware
  zero reads as depth rather than as a level.
- **Status text has no icons at all.** [code — `StatusPanel.qml`] *"Text-only
  system status: a small dim label over a coloured value for each metric. No
  icons, glyphs, or bars — just the pixel font and numbers. Colour still carries
  state."* The weather module uses the condition **word** as its own icon.
- **The progress/usage bar**: `Theme.bgAlt` box + 1px `Theme.border`, fill inset
  `margins: 1`, `width = round((parent - 2) * frac)`. It is built five separate
  times with no shared component; the geometry above is the agreed part.
- **The pin affordance is one dim letter** — a `p` that lights on hover, no
  chrome. Reused verbatim for the clock's face cycler: *"same visual language as
  the popups' pin indicator: one dim letter that lights on hover, no chrome."*

---

## 9. Lists, rows, columns and graphs

### 9.1 Rows

- **Uniform row spacing, full stop.** [his] *"notice how some of the tracks on
  the top left have different spacing between them. that should not be the
  case."*
- **A row highlight is vertically centred on its own text**, and the "current"
  row auto-scrolls to the **middle** of the viewport [his]. Identify it by row
  **index, not by content id** — a queue can hold the same track twice.
  Highlight = background **plus a 2px accent gutter**, so it still reads as the
  current row while the cursor hovers another.
- **Hover-revealed affordances give their space BACK.** [his] *"when the stars
  and hearts are hidden from the queue due to no hovering, the rest of the text
  in the title part should be shown in that area. currently it gets cut off even
  if no stars or heart is showing"*. Note this **reverses** an earlier decision
  to preserve their width to avoid reflow (`520b784` correcting `257803c`) — his
  call, and the later one wins. And **gaining interactivity must not change an
  element's resting appearance**; hidden controls are click-dead.
- **Suppress redundant repeated metadata.** [his, twice] *"the queue list should
  only show the artist name of a track if does not match the currently playing
  track"*. Implementation note from the correction (`46fa9e3`): match on the
  **base artist with the feature tail stripped**, and **split the row into two
  Texts so the title claims width first** and only the dim artist runs off the
  end — there is no ellipsis to disown a half-rendered guest credit.
- **Badges cluster with their kin at the trailing edge** — the play count sits
  next to the duration, not wedged between the title and the numbers.
- **Columns drop out widest-first as the container narrows**, at `width: 0` and
  **not** `visible: false`: the next column anchors to this one's left edge and
  an invisible item keeps its geometry. [code]

### 9.2 Scrolling

- **Every scrollable region has a visible scrollbar.** [his] *"there should be a
  scrollbar wherever appropriate! please"* One idiom everywhere: visible only on
  overflow, brightens on hover/drag, accent while pressed, 120ms opacity fade.
- **Scrollbar and wheel only — never click-and-drag to scroll.** [his] *"the
  user should not be able to click and drag to scroll"*. Qt gives you drag and
  wheel together or neither, which is why the wheel is re-implemented by a
  `WheelScroll` overlay that accepts no buttons.
- **No nested scroll regions.** [his] *"the user should not be able to scroll
  the tracklist in the slidedown. it should display ALL tracks."* A disclosed
  section sizes to its whole content and a wheel notch over it falls through to
  the view underneath.
- **One notch is one meaningful unit** — one cover row, one detent.
- **Momentum belongs to the compositor, and no view adds its own.** [code] Use
  `KineticListView` / `KineticGridView` / `KineticFlickable` (apps:
  `apps/qmlcommon/`; panel: the `Kinetic*` types) — never a bare `Flickable`.
  Two decay curves are two curves fighting, measured at +43% overshoot.
- **Every wheel handler scales by DISTANCE, not by event count.** [his] *"when
  scrolling really slowly scrolls FASTER than normal"*. A sign-only handler
  treats each of a ~125 Hz touchpad stream's events as a full step: viewer's
  zoom crossed its whole range in 12 events, the playbar jumped the song by
  minutes. One classic detent must stay bit-exactly its old step, and
  **zero-delta events are no-ops**, not step-downs.
- **Discrete steppers (volume, brightness, tray) stay notch-based on purpose** —
  they are steppers, not scroll surfaces, and a coast that walks brightness to 0
  is a bug. Use `WheelNotch`, never a sign test.

### 9.3 Graphs and readouts

- **Uniform squares in a grid.** [his] *"can you make the top stat graphs squares
  and add new squares for load, vram, swap, and fan?"* The odd one out becomes a
  horizontal bar rather than an irregular tile. Square means the card height
  follows the panel *width*, so a taller tile shows more processes rather than
  letterboxed charts.
- **A line chart with no key is a squiggle** [code — `d0bf5a4`]: legends are
  mandatory, replaced on hover by the values for the sample under the pointer.
- **A graph, not a table, where the data is a series.** The forecast is twenty
  points in the space a seven-row hi/lo table used, night halves shaded so the
  two-per-day structure reads.
- **A condensed variant is a scaled-down version of the SAME content.** [his]
  *"the condensed weather widget should still show the graph, a condensed
  version of it, like it used to be"*. Condensing drops labels, markers and axis
  text — the parts that stop being readable — never the line, which is what the
  graph is for. Below even that, the graph is dropped **entirely** rather than
  drawn as an illegible sliver. **Every threshold is derived from the constants
  the layout is built from, never a literal** — the literal it replaced forgot a
  label row and three margins, was 24px short, and made everything in that band
  claim it could draw a forecast and then hand the canvas 0-18px. A floor
  mirrored from a content component **must add the host's frame inset** (2px),
  or you are one and a half pixels short forever.
- **Numbers must be honest about time.** CPU% is instantaneous, from two `/proc`
  samples 0.4s apart — not `ps`'s lifetime average; "a task manager whose
  numbers converge after an hour isn't one". Memory is `MemAvailable`, not
  `MemFree`. A battery graph has a **fixed 0-100 axis** — one resting at 96%
  autoscaled against its own peak reads as full-to-empty.
- **A readout must exclude values that CANNOT VARY — and the test is history,
  not level.** [his] *"exclude the pump that one i cannot change even via the
  mobo settings and im pretty sure i cant even hear it anyway"*, then *"i also
  meant just completely remove the pump fan from the widget. i dont need to see
  it at all"*. A constant is not a reading, and a reading he cannot act on is
  not worth the pixels — so the fan card does not draw that fan at all.

  **The obvious rule is the wrong one.** "Exclude whatever is at maximum" would
  delete a chassis fan that has ramped to 100% in a thermal event — the exact
  moment it matters most. And "exclude whatever is not moving" hides almost
  everything: measured at idle, all four chassis duties here sit rock steady
  across a 20s sample. So it takes **both** conditions — at maximum AND never
  once observed to move — with the "has moved" flag STICKY and carried across a
  reload. Anything that has ever answered the machine is drawn for good,
  including while pinned under load.

  Three corollaries, and they get *stronger* as the consequence grows from "a
  different summary" to "not on screen at all". **Nothing is judged before it
  has been watched**, so a fresh widget hides nothing. **The rule may never
  empty the widget**: if it would hide everything, it hides nothing, because a
  display full of constants says more than a blank one. And **whatever you hide,
  surface its FAILURE** — hiding the pump removed the only place a pump failure
  could show, so a fan that stops reporting is re-emitted at 0 rpm and marked,
  where the hide rule can no longer reach it. If a thing is too boring to show
  while it works, it is exactly the thing nobody will notice has broken.

  **And "surfaced" is measured against the consequence, not against the
  widget.** [his] *"yes i absolutely want the pump failer notifaction louder
  yes"*. A row in a tooltip he has to hover a hidden card to find is not an
  indicator for a fault that can cook a CPU. Loud here means all of: a
  **critical** notification — which on this desktop already buys the alarm
  sound rather than the balloon, a Do Not Disturb bypass, exemption from
  toast-stack eviction, and no auto-expiry — sent with an explicit **zero
  timeout** so it waits however long he is away; **plus** the card itself going
  `crit` and naming the fan, because the toast may have been dismissed hours
  ago and the card is what he looks at next.

  **The debounce is the price of being believed.** A false "your CPU is
  cooking" at 3am costs more than a late true one: the alarm is never trusted
  again. So it wants a *sustained* fault — 15 consecutive polls, 30 seconds —
  and every transient cause of a zero reading dies inside that window. The
  thermal margin pays for it: a CPU that loses its pump throttles long before
  it is damaged, so the alarm does not have to win a race, it has to be right.
  Alarms fire **once per episode** and reset when the fault clears, so a second
  genuine failure still speaks.
- **Alternate faces of one widget share their behavioural details** — both
  digital clock faces blink the colon on the same beat, in the same unlit
  colour, so cycling faces changes the look and never the semantics.
- **Status words are terse, terminal-register abbreviations** — `pcld`, `chg`,
  `ac`, `res`, `psi`.
- **Don't trust `comm` for a process name** — the kernel caps it at 15 chars and
  everything here runs through a NixOS wrapper, so it reads `.quickshell-wra`.

---

## 10. Honest affordances

**A control that is drawn is a control that works, and feedback must reflect
reality, not intent.** [his — the deepest recurring frustration in the corpus,
across four sessions and three subsystems]

> *"many if not a majority of the settings do not actually function or do what
> they proclaim"*
>
> *"i dont know what 'reload from disk' does but it certainly does not change or
> apply any settings"*
>
> *"neither the stars or the heart does anything — or at least nothing happens
> that the user can see"*
>
> *"the negative brightness thing didnt actually work… it reports it in the osd
> but doesnt change the screen gamma"*

No inert buttons. No hover state without a working click. No OSD reporting a
change that did not happen. **Settings take effect live, on the fly.**

The engineering corollary [code, stated verbatim in the panel guide]: **an
action `execDetached` cannot report on must not be OFFERED.** There is no exit
code and no stderr, so signalling another user's process — or launching a binary
that is not on PATH — is a *perfect silent no-op*. Hence:

- **A row that is not ours gets the read-only entries and a line saying why** —
  not a greyed-out button with no explanation, and not one that does nothing.
- **Route launches through `NixPath`** and register new launch targets. On book
  the panel's PATH is Fedora's only; `hyprsunset` was missing for its entire
  life there and night light silently never existed. "Silence, not breakage, is
  what let this rot unnoticed for so long."

### 10.1 One control, one effect, and the effect is its label

[his] *"play album should not send the user to the gallery view and search, that
should be its own option 'search for artist'. play album should just replace
queue with that album and stay on the now playing view"*. **An action never
navigates you somewhere as a side effect.**

**A control acts on the state you can SEE.** [his] *"clicking on a rolled up
windows button on the panel shouldnt put that window in focus. it should unroll
the window."* The rolled-up state is the visible obstacle, so that is what the
click removes.

**A button reports its OWN state, not the feature's** [code — `fc73fed`]: the
`dm` button lights only while its panel is open, "not for the whole time dark
mode is globally enabled".

**A control's pressed/active visual is reserved for actual user interaction.**
[his] *"during the opening and closing animations for windows, the roll up/down
button should NOT show as being activated"* — the animations borrow the roll
machinery internally, and that must not surface as a pressed-looking button.

### 10.2 Refuse visibly; never no-op

- **Decline, don't ignore.** viewer's panes decline non-media and non-local
  drops "so the source shows a refused drop instead of a silent no-op".
- **Refuse and disable together.** filer's split button is disabled *and*
  `toggleSplit()` refuses, in a picker where split makes no sense.
- **Fake it only where you own it.** Shuffle is dimmed when unsupported "since
  it can't be faked without owning the queue"; repeat *is* faked (seek-to-0)
  only where MPRIS lacks `LoopStatus`.
- **Hide a control whose reading does not exist, and let it come back on its
  own.** The chassis-fan bar hides itself where there is no tachometer; "it
  lights up by itself if that ever changes".
- **Ask when you genuinely cannot know.** A drop offers `move / copy / link
  here` because the modifier keys never reach the destination process under
  Wayland — **"guessing would mean silently moving the user's files on a
  hunch"** (`2ec6f34`).
- **Never silently clobber.** Free names run immediately; conflicts are held for
  a confirm.
- **Warn before a long operation, and report it with the EXISTING toast
  component** [his] — *"if it doesnt think the conversion will be quick warn the
  user before confirmation. also give it a status toast like file moving does"*.
- **An app that cannot do its job says so instead of opening broken** [his] —
  *"for player, on air/book if it cant reach top to show the library then it
  should just tell the user and not open"*.

### 10.3 Destructive actions are two deliberate acts

[code — `67c7979`] SIGKILL is a menu entry, never a click on a table that
re-sorts under the cursor every 2s. **And the panel is not offered a way to end
itself**: no `[x]` on its own row, the menu reads `this is the panel - signals
refused`, and the call site refuses its own pid a second time. "The bar, the
wallpaper and every popup are one process; there is no undo and nothing left on
screen to explain what happened."

### 10.4 Notify once; persist while true

[his — stated for two entirely different systems in the same session, which is
what makes it a principle rather than a bug report]

> *"longer downloads just trigger the toast over and over instead of staying on
> the screen until they are finished"*
>
> *"i want it so that you, claude-code the harness, stops sending subsiquent
> notifications after sending the first… just do it once lol"*

**A status toast for an ongoing operation stays on screen until it finishes and
is morphed in place; it does not re-fire.** Honour the freedesktop spec:
`expire_timeout 0` means never expire, `>0` is an explicit lifetime, and a
replacement **restarts** the countdown. Eviction spares a persistent toast
exactly as it spares a critical one. Senders must ask for it (`-t 0` on every
progress update, the default timeout on the final one).

A toast is **sized to its label plus padding** — a fixed slab was rejected
because "'recording…' never needed that much room".

### 10.5 Two percentages on one screen share one denominator

[code — `proc-list.py`, 2026-07-27] The task manager's `cpu%` column sits under a
cpu card reading 0-100 and reported 0-**1600**: it was `top`'s **Irix mode** (a
share of ONE core) against a gauge computed from whole-machine total-vs-idle
deltas. Both numbers were correct and together they were a lie, because nothing
on screen said the two `%` signs had different denominators — the user's
question was simply why a process said 400. It is now **Solaris mode**, divided
by the CPU count taken from the same `/proc/stat` CPUs the gauge sums. (`top`
ships both and toggles them on `I`; a desktop widget has no `I` key and no room
to caption itself, so it picks the one that agrees with its neighbour.)

**A denominator is part of a number's meaning, and a widget cannot state it in
the space it has** — so two readouts of one quantity that can be seen at once
take the same one. Where a surface genuinely cannot (the fan card's percentage
is commanded duty against its own full scale; sysfs publishes no maximum RPM, so
there is no honest denominator and one is not invented) it says so in the
tooltip and keeps the exact figure there.

**Rescaling a column means retuning everything read against it in the same
commit** — colour thresholds, bar scales, precision. A threshold left at its old
scale does not break visibly; it just stops meaning anything, which is worse.

---

## 11. Focus, pointer and input

**Visual focus and input focus are the same thing, always.** [his — four
sessions]

> *"when i then focus on another window, it acts as if i have clicked and held
> onto that spot when really i have only clicked"*
>
> *"if two titlebars overlap and at least one of them is rolled up, grabbing on
> an area with both under will move both windows instead of just the one on top"*
>
> *"when i said clicking out of the filter bar returns focus from the filter
> search, i meant anywhere on the desktop not just anywhere in the bar"*

**A click lands on exactly the topmost thing under the cursor. A text field
releases focus on a click anywhere else on the desktop, not just within its own
container. Never a state where the user must click twice.**

**Click-away dismisses, and "away" means the whole desktop.** [his — the third
quote above is the rule in his own words] A click anywhere outside a control
that holds focus drops that focus, **wherever it lands** — including the parts
of the screen that are not the app's and not the panel's.

**There are THREE cases, not two, and they are split by what the click lands
on** [code — measured in a nested-Hyprland harness, `8d292b5`]:

| the click lands on | who drops the focus |
|---|---|
| the **panel** | ours — `shell.qml`'s catcher, on `barBody` |
| a **window** | the compositor's, and it needs no click at all: the layer surface's keyboard is revoked on pointer **entry** |
| the **wallpaper** | ours, and this was the bug |

The wallpaper was the missing case. Hyprland's `processMouseDownNormal` calls
`refocus()` only when the press lands on a *window*, so a press on a
**Background** layer surface moved no focus whatsoever and the filter bar kept
the keyboard. **Both halves of the previous belief were wrong** — the panel's
own guide described two cases, not three, and named `dockLayout` as the catcher
when it is `barBody`. Which is why the case split above is written down here: it
was reasoned about twice and only settled by measuring.

Two hard-won compositor rules behind that [code]: **chrome under something else
declines input** (no resize cursor over an occluded edge; a rolled-up bar renders
below windows so anything at the cursor occludes it), and **the keyboard is
handed back to a WINDOW, never to nothing** — dropping a layer surface's
on-demand focus while the pointer is still over the panel leaves the compositor
focused on nothing and the keyboard dead until the user clicks.

**That second rule is narrower than it sounds, and the difference is measured**
[code — `8d292b5`, correcting the fear left by `cf26f82`]: dropping to `None`
from the **wallpaper** does *not* strand the keyboard. `refocusLastWindow`
searches only the **OVERLAY** and **TOP** layers, so it can never find a
Background surface under the pointer and can never hand the keyboard straight
back to the thing the user just clicked away from. "Never to nothing" is about
on-demand focus dropped **while the pointer is over the PANEL**. Do not let the
scarier reading of it block a fix on a different layer — check which layer the
surface is in first.

**The resize does what the cursor icon promises.** [code — `c659ddf`, `7736c46`]
Hyprland's native resize picks a corner by window *quadrant*, so grabbing the
middle of a side moved two edges while the cursor showed an edge icon. Side →
that edge only; corner zone (border + 10px, matching the icon's zones) → two
edges. The right-edge handle engages **only at the very edge**, like the other
sides, so mid-titlebar clicks drag.

**Standard platform conventions work everywhere, unprompted** [his]: mouse
back/forward buttons, `Ctrl+scroll` / `Ctrl +/-` zoom, `Space` for play/pause
(and clicking out of a text box restores it).

### 11.1 The mouse's side buttons navigate history — in EVERY program

> [his] *"back and forward mouse buttons should function in every program.
> takes the user back and foreward"*

The clearest instance of §0's default there is: he named no program, so it binds
all of them. `Qt.BackButton` / `Qt.ForwardButton` — evdev `BTN_SIDE` (275) and
`BTN_EXTRA` (276), both advertised by the trackball on `top` — walk the
program's own history, from anywhere in its window.

**One implementation, not seven.** `apps/qmlcommon/NavButtons.qml` is the
handler (a full-window `MouseArea` that accepts *only* those two buttons, so
every other press, wheel notch and hover still falls through to what is really
under the cursor — which is why it can sit at `z: 9000` harmlessly), and
`apps/qmlcommon/NavHistory.qml` is the browser-style stack behind it: going
somewhere new drops the forward stack, and both stacks are REASSIGNED rather
than mutated, so `canBack`/`canForward` actually notify. The panel keeps
parallel copies (`quickshell-files/NavButtons.qml`, `NavHistory.qml`) for the
same reason `PixelText` and `Kinetic` are duplicated — two roofs, no shared
file (§19).

**"Back" means whatever that program's history is, and the reading is the
program's subject matter, not a free choice** (§0.1 rule 2):

| surface | back / forward |
|---|---|
| `[surfer]` | page history — `current.goBack()/goForward()`, the focused pane |
| `[filer]` | **directory history**, per pane, on the FOCUSED pane. Not the parent — the titlebar's `^` already means parent, and they are different journeys. filer had no history at all; building one was part of the rule |
| `[viewer]` | previous / next in the flip order, on the FOCUSED pane — the same move as `‹`/`›` and the arrow keys |
| `[player]` | the **view** you came from, not the previous track. Transport already owns prev/next, and taking the side buttons for it would leave no way back out of an album |
| `[panel]` | the file browser's directory history. It is a real `FloatingWindow` the user browses in |
| `[painter]` | **nothing, deliberately.** Its gallery is a newest-first output list with no cursor, its params/gallery switch is a 2-state toggle (and above 900px both panes are visible at once), and it has no prompt history and no undo. There is no journey to retrace, and inventing one would mean inventing the state first |
| `[askpass]` | nothing — a modal password prompt has no history |

**Where a program has no history, the buttons do nothing, and that is the
correct outcome.** A button that surprises is worse than one that is inert —
§10's honesty rule cuts this way too. Say so here rather than inventing a
navigation to hang on it.

**The compositor deliberately leaves buttons 8/9 unbound.** `hyprland.lua` binds
only `mouse:272` (left, with `mainMod`, for window drag), and `hyprvtb`'s
pointer-button listener is a passive observer that never cancels the event — so
the buttons reach the focused client untouched. Do not add a global bind for
them: it would take them away from every program at once, which is the opposite
of the rule.

Regression test: `apps/filer/tools/nav-test.py` posts real `QMouseEvent`s
carrying those two buttons at an offscreen `Main.qml` and asserts the history,
the forward-stack drop, that a left click still reaches the pane underneath, and
that back moves the focused pane only.

**Floating windows raise on focus** — activation without raising "read as
'nothing happened'". Alt-Tab walks **MRU focus history with a frozen snapshot
per walk**, so tab-tab-tab digs deeper like KDE's switcher rather than bouncing
between two windows.

---

## 12. Window chrome and the titlebar

**The titlebar is VERTICAL, on the window's RIGHT edge, and the COMPOSITOR draws
it.** [code] `hyprvtb`, `DECORATION_EDGE_RIGHT` — "locked to windows
frame-for-frame, the thing no layer-shell client can do". Two prior
architectures (60Hz drag-follow layer surfaces; a single overlay with occlusion
clipping) were built and deleted before this one.

It is two columns wide: the **outer** column is the five system cells (close,
maximize, minimize, pin, rollup) plus the stacked title; the **inner** column is
the app's own buttons, registered over a Unix socket by `apps/pylib/vtbclient.py`.

**The titlebar is PART OF THE WINDOW.** [his — he had to say it three times in
one session] *"i think youre only pushing the literal program window out of the
way and not the titlebar as well. it should be both"* … *"just to confirm the
titlebars (even rolled up ones) should move out of the way as well"* … *"rolled
up titlebars are still not pushed into the new desktop area"*.

Any operation on windows — reflow, push, move, remember-position — treats the
decoration as belonging to the window, **including rolled-up ones**, which is
the case agents keep forgetting. Mechanically: `hyprctl clients` reports the
*client* rect and reports decoration extents nowhere, so reconstruct the frame
from `plugin:hyprvtb:{enabled,bar_width}` + `general:border_size`.

**An app must not draw its own chrome strip.** filer had a right-edge button
strip inside its own window that "visually merges with the real
compositor-drawn titlebar but isn't actually part of it"; it was deleted and its
buttons moved into the real bar.

**The outer titlebar shows live document/state identity, not the app's name.**
[his] *"move the artist / title text on the inner titlebar and move it to the
outer titlebar while removing the 'player' text"*.

**Guard every rect you hand hyprvtb.** Hyprland's `renderRect` *aborts the
compositor* on a zero-size box — the player's paused-at-0:00 progress bar took
the whole session down.

### 12.1 Button vocabulary

**Buttons are plain pixel-font glyphs — never Canvas drawings, never an icon
font.** [code — `6442834`, `985e672`] Established glyphs:

| function | glyph |
|---|---|
| close / maximize / minimize | `x` / `=` / `>` |
| pin | `o>` |
| roll up, and rolled | `>>`, flipping to `<<` |
| play / pause | `>` / `\|\|` |
| previous / next | `<<` / `>>` |
| shuffle / repeat | `*` / `o` |
| split (kitty's, and therefore everyone's) | `\|` and `_` |

The last row is [his], verbatim: *"the split buttons for both surfer and filer
should be the same as with kitty, `|` and `_`"*. The transport row is [his] too.
**A function that already has a glyph keeps it in every app.**

Labels are one or two ASCII characters. **Button ids must not contain `:`** —
it is the wire separator, and `sort:name` broke once. (Labels themselves may
hold any character; `vtbclient.py` percent-encodes. §2.3 still limits what you
can legibly *draw*.)

**An active toggle is INVERTED: filled with accent, glyph in the background
colour.** [code — `6c0a956`] Rejected: accent-on-transparent. Hover is the
lighter `bgAlt` tint. Per-entry state is `normal` / `lit` / `disabled`, and a
lit cell greys to the inactive tone on an unfocused window.

**A pressed cell inverts for 220ms** (`VTB_FLASH_MS`) — fills solid, glyph in
the bar background, then reverts. Actions whose result is instantly visible
(close, minimize) never show it; everything else confirms the click.

**Roll-up is a true hide with geometry untouched.** [code — `cf54b94`]
Rejected: collapsing the window to 1px, which fought client min-size (browsers
left a sliver) and restored to a saved pre-shade position, so a shaded window
that had been moved snapped back on unroll.

---

## 13. Drag and drop

**Dragging works between windows and between apps, like a normal file manager.**
[his] *"can we get window to window file dropping working on filer? having two
windows open and dragging files between them"*; *"i should then be able to drop
any image into any split view"*.

- **The cursor carries a drag chip** — a small badge with the filename, grabbed
  to `Drag.imageSource` on press, structured so it can become a thumbnail later.
- **The payload is built on PRESS, not bound** — a binding re-runs it for every
  realised row on every selection change.
- **A drag carries the whole selection** when it starts inside one. That needs
  the press *not* to collapse the selection: defer the click to the release and
  apply it only if no drag happened.
- **The target highlights while the drag hovers it.**
- **A drop ASKS what it meant** — `move / copy / link here` (§10.2).
- **A multi-drop fills the pane it landed on and opens NEW panes for the rest**,
  never overwriting panes the user arranged. A short last row has its final pane
  **span the leftover columns rather than leave a hole**.
- **Transfers reuse the paste machinery**, so a drop inherits the no-clobber
  default and the overwrite confirm rather than growing a second, laxer path.
- **Never decode a uri-list in QML** — `encodeURI`/`decodeURI` leave `#` and `?`
  mangled, which was a real filer bug. `QUrl`, in Python, once.

---

## 14. Cross-app continuity and persistence

**Every user-adjustable visual state persists across reload AND logout.** [his —
four sessions] *"ensure any changes the user makes to any of the widgets is
saved and remembered between reloads/relogs"*; *"the bar should remember how the
user changed the clock style"*; *"allow the user to drag the handles in between
all sections and keep it across sessions"*; *"the album cover browser page should
always remember where the user was on the page so it can return to that exact
spot"*.

**Anything the user changes by USING a widget goes in the persistent store, not
a local property, and not a reload-only slot.** The test is whether they would
notice it reverting. In the panel that is `SettingsStore` plus an explicit
`save()` — without the save the polling reader reverts it within the second, and
three settings shipped that way and quietly forgot what he chose. Apps use their
own `$XDG_CONFIG_HOME/<app>/*.json`. Transient state (a hover index, a filter
query you are typing right now) stays local, deliberately.

**A child window inherits the parent's view state and then holds it stable.**
[his] *"imagine the user has the filer sorted a certain way and clicks on an
image in the dir to view it with viewer. viewers left and right arrows should
corrispond to the order in which the dir is in that parent instance. for if the
user then goes and changes the order while the viewer is still open, just keep
the order the same in viewer"*. Handed over at launch, consumed on read, frozen
after.

**Don't throw the user out of the view they are in.** An album opens as an
inline section that pushes rows down, not as a separate page; leaving for
another view is its own explicit action.

---

## 15. The wallpaper and the desktop surface `[panel]`

- **The wallpaper is composed against the VISIBLE desktop area, not the raw
  screen** [his] — *"the middle of the wallpaper matches up with the middle of
  the available non-panel desktop space"*. It re-centres as the panel resizes.
- **Gaps are never black.** [his] *"the empty black space when the user drags
  the panel to the right… lets fill that with a super blurry version of the
  wallpaper, dont scale it or anything to increase cpu usage, just a staic super
  blurred version"* — then *"even more blurred and of better quality, way more
  blurred and better quality"*. It is a **pre-computed real Gaussian**, cached
  per wallpaper, **PNG not JPEG** (the output is nothing but smooth gradients,
  exactly what JPEG bands). A cheap bilinear upscale was tried and rejected:
  "it is free, but it is not a blur — rendered out and looked at, the picture
  was still plainly legible with interpolation facets".
- **`sourceSize` must never be bound to an item's width** — it would re-decode a
  multi-megapixel image every frame of a drag.
- **Desktop widgets live strictly BELOW windows** [his] — "they obviously should
  be seen underneith all windows".
- **A wallpaper change is a cross-fade, never a flash.**

---

## 16. Web pages as a design surface `[surfer]`

**The desktop's font may be imposed on a page; the desktop's sizes and colours
may not — and the choice is per-site.** [code — a clean escalate-then-retract
arc: `8c76d7a` family-only → `d9653f5` full reskin "per request" → `ad868e4`
*"Scratch the full system-style reskin"*]. Family only, so site font-sizes stay
and heading hierarchy survives; forcing size and palette too is reader-mode
territory and breaks real sites.

**Dark mode never touches images.** Media gets the filter's *exact* inverse (the
reversed sequence of per-function inverses) so images come out pixel-identical
at any brightness/contrast setting, not just at the defaults a naive
double-invert happened to preserve.

Page scrollbars are wal-themed — the palette reaches inside the page.

---

## 17. Sound

**A narrow, deliberate set of Vista event sounds; ambient click feedback was
tried and abandoned.** [code — `42473b8` → `efa6b90` → `526f79d`, a three-step
retreat in two days] A global click on every left press became a click only
where a click *does* something, and was then removed entirely along with
minimize and restore. **The survivors are: logon, notification balloon /
exclamation, volume ding, trash recycle, UAC prompt chime.** Mount toasts were
also silenced as noise.

**Do not add a sound to a new action without asking.** The history says the
default answer has been no.

---

## 18. Desktop-wide laws, and things this desktop deliberately does NOT have

Two compositor settings shape every interaction and are stated nowhere in the
`AGENTS.md` chain:

- **`input:follow_mouse = 2`** — pointer focus follows hover, so **scrolling
  scrolls the window UNDER the cursor**, while keyboard focus still only moves
  on click. Reason about scroll targeting with that in mind.
- **The desktop is locked to a SINGLE workspace, by design.** The panel is a
  program taskbar, not a workspace switcher. Every workspace bind and the
  3-finger gesture were removed. **There are no touch gestures at all.**

**Intentional non-goals — do not "add the obvious missing thing":**

| absent | status |
|---|---|
| a window/workspace overview | deliberate; single workspace |
| a screen-recording OSD | deliberate |
| mic-mute and caps-lock OSDs | deliberate |
| an unlit grid behind the dot-matrix clock | deliberate (§3.4) |
| a disk tile in the dock | classic-mode only, by choice |
| bold or italic type | impossible with this font, accepted (§2.2) |

**Known, accepted gaps** (not non-goals — just not done): `Lock.qml` is a clock
over solid black; notifications render no images, no actions and keep no
history; and **`wal-set.sh` recolours everything except GTK and Kvantum**, so
Firefox's chrome and GTK dialogs do not follow the wallpaper.

---

## 19. Where the shared pieces live

| shared thing | canonical home |
|---|---|
| the palette | live `~/.config/quickshell/Theme.qml`, written by `wal-set.sh` |
| panel geometry + font size | `SettingsStore` → panel `Theme.qml` |
| **app** font family + size | the same `settings.json`, read by `apps/pylib/deskstyle.py` → each app's `Theme.qml` |
| app theme | `apps/<app>/qml/theme/Theme.qml` (six byte-identical copies) |
| pixel text | `PixelText.qml` (panel + one per app) |
| glyph mapping for foreign text | `quickshell-files/Glyphs.qml` — **panel only** |
| scroll physics (panel) | `quickshell-files/Kinetic.qml` |
| scroll physics (apps) | `apps/qmlcommon/` + `apps/pylib/kinetic.py` |
| discrete wheel steppers (panel) | `quickshell-files/WheelNotch.qml` |
| discrete wheel steppers (apps) | `apps/qmlcommon/WheelNotch.qml` — the twin, same algorithm |
| mouse back/forward (apps) | `apps/qmlcommon/NavButtons.qml` + `NavHistory.qml` (§11.1) |
| mouse back/forward (panel) | `quickshell-files/NavButtons.qml` + `NavHistory.qml` — the twin |
| titlebar buttons | `apps/pylib/vtbclient.py` → `hyprvtb` |
| launching binaries | `quickshell-files/NixPath.qml` |
| settings widget vocabulary | `quickshell-files/Set*.qml` |

**`apps/qmlcommon/` is the place for QML every app needs**, reached with
`import "../../qmlcommon"`. A component that exists in two apps belongs there.

**The scroll feel is defined in THREE hand-synced places** and the repo says so
itself: `hypr-files/hyprland.lua` (both seed-once copies, the
`plugin:hyprvtb:kinetic*` keys — the authority), `quickshell-files/Kinetic.qml`
(`friction 3.6`, `flickDeceleration 2160`, anchored at a 1200 px/s flick), and
`apps/qmlcommon/`. *"They are two files, so it is a hand-copy, and that is the
one duplication the design could not remove."* Retune one, retune all three.

### 19.1 What has silently diverged

Findings, not rules — every one of these is a real inconsistency today:

| what | state |
|---|---|
| `apps/*/qml/theme/Theme.qml` | six **byte-identical** copies, kept in sync by hand |
| App LAYOUT vs font size | fixed. The six apps now track the same setting the panel does (§2.1), but their *layouts* were sized against 15: painter derives nothing at all from `Theme.fontSize`, and player, filer and surfer each keep a handful of literal row heights and column widths. See §2.7 |
| `Theme.inactive` | present in all six apps, absent from the panel's Theme |
| `Glyphs.px()` | **panel only.** The six apps draw filenames, ID3 tags and page titles with no mapping, so §2.3's clipping applies to them unmitigated — and he explicitly asked for it to be wired "through the others" |
| `PixelText.qml` | 7 copies; behaviour identical, comments differ |
| `CtxMenu.qml` | identical in filer and player; surfer has a separate `ContextMenu.qml` |
| `VScroll.qml` | identical duplicate in player and painter |
| `Slider.qml` | player's and surfer's have diverged |
| `BrowserButton.qml` | three different files in filer, surfer and the panel |
| Tooltip dwell | panel 350ms, hyprvtb 450ms |
| Slide duration | 220ms almost everywhere, but `player/qml/SettingsPanel.qml:39` is 200ms and `player/qml/AlbumGrid.qml:171` is 130ms/`OutQuad` |

Where a divergence has a clear correct side it is: **the panel's value wins for
anything the panel also draws**, and **anything duplicated byte-for-byte between
two apps belongs in `apps/qmlcommon/`.**

**painter WAS the outlier app** — it broke eight rules in this document at once,
and the whole set was closed in one pass. The list is kept because the *pattern*
was the finding, and because each entry now names the shape the rest of the tree
should be checked against:

| it did | it now does |
|---|---|
| six `radius:` values, where every other app has zero (§4) | zero |
| a `QtQuick.Controls.Basic` `ToolTip` in the **system font and system palette** — the only place a non-pixel font could appear on this desktop (§2.1, §8) | its own `ToolTipArea`: 350ms dwell, 220ms `OutCubic` clipped slide out of a fixed left edge, `bgAlt` + 1px `border`, `PixelText` |
| no button component at all — clickable `PixelText`, no hover, no `cursorShape` on any of its 29 `MouseArea`s, no disabled state (§4, §10) | one `TextButton.qml`: player's `HeaderButton` idiom + filer's `BrowserButton` `enabled`/`winActive` semantics, and `cursorShape` on every remaining hit target |
| `PreferNoHinting` on its text inputs, contradicting `PixelText` (§2.2) | `PreferFullHinting` |
| zero use of `Theme.inactive`, so its content stayed bright while the titlebar greyed (§3.1) | `root.fgAccent` on its accented chrome, filer's idiom |
| UPPERCASE titlebar labels and `*` for settings (§12.1) | `gen` `x` `p` `g` `st`, and lowercase section titles |
| a **centred modal with no animation** for settings (§7.4, §6.2) | a bottom-right drawer sliding out of the `st` cell that owns it, built like player's `SettingsPanel` |
| wheel constants re-derived locally (§9.2) | `qmlcommon/WheelNotch.qml` — and note the reclassification: a `Spin` is a **discrete stepper**, so it takes the notch accumulator, not `WheelScroll` |
| three controls that never reflected state — `[ start ]`/`[ stop ]` always live, `stopBackend()` reporting "backend stopped" without checking the return code (§10) | `App.backendRunning` polls `systemctl --user is-active`; start/stop/unload light and refuse from it; `stopBackend()` toasts systemd's own failure; `unloadModels()` waits for the `/free` reply instead of claiming success on a POST |

**player's settings panel remains the reference for a settings drawer** in this
tree: it flips its own label to `scanning`, lights up, and guards the handler.

Two things that pass came out of that pass and are worth carrying:

- **`enabled` is `Item`'s own property — do not redeclare it** on a button
  component. Shadowing it warns at load and leaves the base property still
  disabling the subtree underneath, which is the behaviour you wanted anyway.
- **`lineHeight`/`lineHeightMode` are `Text`-only.** `TextEdit` does not have
  them, so assigning them is a component-creation *error*, not a no-op.
  `21534ca`, the kitty-exact pass, added them to painter's `PromptBox` by
  analogy with `PixelText`; that made `PromptBox` unavailable, which took
  `PromptEditor` and then the whole of `Main.qml` with it. **painter could not
  start at all between that commit and this one.** A multi-line editor therefore
  leads at Qt's rounded 16px, not kitty's 15px cell — accepted, and the comment
  in that file says so.

**Two more honesty findings, outside painter:**

- **`viewer` uses non-ASCII in six of its eight titlebar labels** (`‖ ▶ ‹ › − ×`)
  and filer uses `↑`/`↓` — glyphs the font does not have, in labels the plugin
  draws in that font (§2.3). askpass is the only app that enforces ASCII-only.
  This is the largest single cluster of §2.3 violations in the tree.
- **Six settings are declared, shown in the Settings UI, and consumed by
  nothing**: `themeMode`, `accentOverride`, `paletteColorCount`, `pureBlackBg`,
  `reduceMotion`, `animSpeed`. `pureBlackBg` can never work — `BG` is hardcoded
  `000000` in `wal-extract.py`. Per §10 this is the exact failure he named
  (*"many if not a majority of the settings do not actually function or do what
  they proclaim"*), and it is the largest gap between the documented design
  system and the built one.

---

### 19.2 Second-pass findings — behaviour, states, strings

§19.1 came out of a pass over `Theme.qml`, the QML, the area guides and the git
log, so it found *appearance*. A second pass looked where that one structurally
could not — non-default states, keyboard vocabulary, failure paths, wording and
ordering. **Findings, not rules.** Fixed ones are struck; the rest are ranked by
how badly they read, and the ones marked **RULE?** are his to settle, not an
agent's.

**Fixed in the same pass** (each was a ratified rule already, applied):

- ~~`BrowserConfirm` (both copies) had no keyboard handling at all~~ — Escape
  now cancels, as it always has in `BrowserPrompt` beside it. The *destructive*
  dialog was the one that needed the mouse. Enter stays unbound on purpose.
- ~~`Media.queueAvailable` was `connected && queue.length > 0`~~ — so
  `MediaContent`'s empty-state label, drawn only when the queue *is* empty,
  could never take its `"queue is empty"` branch. A running player with nothing
  queued always read `"player not running"` (§10).
- ~~filer's preview tiles drew `▢` / `✕` / `…`~~ and ~~viewer drew
  `"loading…"`~~ — all four absent from the font (§2.3), so every not-ready,
  failed and loading tile clipped. Now `■` (which the font *does* have, §3.4),
  `x` and `...`.

**Open, ranked:**

1. ~~**filer reports success for every file operation that fails.**~~
   **Fixed.** `FileOps.run` (`apps/filer/main.py`) now reads the exit code and
   raises a critical toast carrying the helper's own stderr, through
   `videoconv`'s toast path (extracted to `filer/notify.py`, one implementation
   for the app). Four states that used to be one: **succeeded**, **failed**
   (`copy failed` + `cp: … Permission denied`), **could not be started**
   (`cannot run gio` — a missing binary is a different sentence and a different
   fix), and **partly failed** — a ten-item paste is ten processes, so
   `beginBatch`/`endBatch` reports `copy: 3 of 10 failed` once instead of a flat
   verdict either way. The no-clobber flags exit 0 when they skip, so the
   overwrite confirm is untouched: a conflict is still a dialog, never a toast.
   Regression test `apps/filer/tools/fileop-test.py` injects real failures (a
   chmod 500 dir, a root-owned destination, ENOSPC via `/dev/full`, a missing
   binary). **It hid a second bug for filer's whole life:** `gio` was on no PATH
   the app could see, so *trash* — the safe default delete — did nothing at all,
   silently, while the selection cleared and the list refreshed
   (`home/prog/filer.nix` now puts `glib` on the wrapper's PATH). §10's
   "silence, not breakage, is what let this rot unnoticed", exactly.
2. ~~**The panel's own two menus are the desktop's only Title Case menus.**~~
   **Fixed.** `ProcMenu` and `TaskMenu` are lowercase (`end task`, `force quit`,
   `copy pid`, `filter by name`, `close`), and §7.2 now states the rule.
   (surfer's 20-item context menu stays Sentence case — it mirrors Chromium's
   wording — but surfer's own titlebar tooltips are lowercase, so the app
   disagrees with itself one click apart. Still **RULE?**.)
3. ~~**`ProcMenu` puts the two destructive entries FIRST**~~ — **fixed.** The
   order is now `filter by name` / `copy pid`, separator, `suspend`|`resume` /
   `lower priority`, separator, `end task` / `force quit`, so the pointer's
   landing spot is a read-only action and the two signals are last behind a
   separator (§10.3, §7.2). `TaskMenu` likewise: `close`, separator,
   `force quit` — repainted `Theme.crit`, since it is the same action `ProcMenu`
   already painted `crit`. **No confirmation dialog was added**, deliberately:
   §10.3's "two deliberate acts" is already satisfied by the right-click that
   opens the menu (that is exactly why the `[x]`'s instant SIGKILL became a menu
   entry in the first place), the popup has no focus grab to host a modal, and a
   second popup in this file is the shape that took the panel down (`7ebd55d`).
   Re-raise it if a mis-kill ever actually happens.
4. ~~**The apps' context menus hover-LIGHTEN**, against §7.2.~~ **The document
   was wrong, not the apps** — see §7.2's own note. §7.2's "hover fills
   `Theme.bg`" had been promoted from `TaskMenu`'s incidental code; hover
   lightens everywhere else on this desktop, `highlight` is the selection fill,
   and the three apps were the majority. The rule was corrected and the panel's
   two menus now take `Theme.highlight` too. (Precedent: §2.2's `Text.elide` ban,
   also promoted from code and also measurably false.)
5. **§7.1 gaps.** player's track list — its most-used list — has no context
   menu, nor do the queue or `PlaylistsView`; viewer *accepts* `RightButton` and
   then discards it, so nothing else can offer one; painter's gallery binds
   right-click to a hidden direct action and needs a permanent caption to be
   discoverable. The tray is the one menu on the desktop drawn by another
   toolkit (`QsMenuAnchor`), against §7.2.
6. **Keyboard vocabulary is per-app, not desktop-wide.** filer has no shortcut
   for any file operation and no arrow-key navigation in its list or grid;
   surfer — the browser — has no find-in-page, no tab shortcuts and no
   `Alt+Left`, while *player* wires the mouse's side buttons and `Ctrl+F`;
   painter's gallery has no keyboard handling at all. Escape means four
   different things across five apps (quit / cancel the queue / dismiss the
   innermost thing / nothing). **RULE?** — each is locally defensible; what is
   missing is a stated vocabulary. askpass is the reference implementation of a
   dialog's keyboard contract.
7. **Ordering conventions disagree.** filer sorts hidden entries above
   everything, surfer's picker sorts directories first and interleaves hidden by
   name, the panel's browser does dirs-first only — three comparable file lists,
   three group orders. filer's location-bar completion (`main.py`) is the one
   **case-sensitive** name sort in the tree, and its prefix match is
   case-sensitive too, so `doc` never finds `Documents`. **No list anywhere
   sorts numerically**, so `track2` follows `track10` everywhere.
8. **`♫` and `♥` are not in the font** — verified, `glyphIndexesForString`
   returns 0 for U+266A, U+266B and U+2665. `MediaContent.qml` draws `♫` under a
   comment asserting it is "the CP437 note glyph"; player's `NowPlaying` draws
   it at `pixelSize: 60` and `♥` in two places. **RULE?** — unlike `…`/`×` these
   have no ASCII equivalent, so replacing them is a design decision, not a
   sweep. §2.3's list was right; the comment is wrong.
9. **There is no loading idiom.** One spinner exists on the whole desktop and it
   is in the plugin's C++ (surfer's tab). Everything else — disk scan, weather
   fetch, library rescan, thumbnail decode — is static dim text, in three
   grammars (`reading...` / `checking...` / `scanning`, the last without dots).
   Empty states likewise come in three (`no X` / `nothing …` / `X is empty`),
   and the tray draws no empty state at all where every sibling widget does.
10. **Wording, small but visible:** `"up a directory"` and
    `"new file or folder"` four lines apart in filer's own button strip;
    `"search artist"` vs `"search for artist"` in one app; askpass's `OK`/`Cancel`
    against everyone else's `ok`/`cancel`. The ellipsis convention (an action
    that opens a dialog gets `...`) is followed perfectly inside filer and
    nowhere else — the panel's own `FileBrowser` offers the same four operations
    with the opposite convention.
11. **Two icon paths for one app.** `TaskCell` resolves through
    `DesktopEntries.heuristicLookup` and degrades to a letter; `Launcher` uses
    `entry.icon` verbatim and degrades to the freedesktop generic. For an app
    whose window class ≠ desktop-entry name — the case `TaskCell` says it was
    written for — the launcher tile and the task cell can show different icons
    for the same program. Four surfaces, four fallback strategies (letter /
    generic / note glyph / nothing). Material for Open question 6.
12. **player's `cursorShape` coverage is 3 of ~21 `MouseArea`s**, including the
    track row and the favourite heart. filer and surfer set it on a third to a
    half of theirs. (painter's was fixed in the painter pass.)
13. `QueueBar`'s fill omits the `round()` §8.1's progress-bar geometry calls
    for, and player's `AlbumGrid` uses `Theme.textDim` for an empty state where
    the same app uses `Theme.dim` twice — the token whose own comment reads
    *"empty & unviewed"*.

**Justified, so nobody re-files them:** surfer imposing only the font family on
pages (§20); painter's gallery sorting newest-first (a generation queue is
chronological); askpass's UPPERCASE captions (§7.5 gravity, and coherent);
filer's `compress to <10MB` carrying no ellipsis (it only asks when the estimate
is bad); `ProcMenu`/`TaskMenu` not honouring Escape (they are `PopupWindow`s
with no focus grab, so `Keys` would be dead code — but §7.2's wording implies
otherwise and should say so); viewer keeping bare `+`/`-` zoom where surfer
cannot (a web page owns those keys).

---

## 20. Recorded exceptions

**Every deliberate divergence from a rule above lives here. A difference that is
not in this table is a bug** — either bring the code back into line, or add the
row. Adding a row is part of the commit that creates the divergence, not a
follow-up (§0.2).

`status` is the same provenance vocabulary as the rest of the file, plus one
more: **`candidate`** means an agent proposed it and he has not ruled. A
`candidate` row is **not** a licence to keep the divergence, and it must have a
matching entry in [Open questions](#open-questions). Concurrent agents finding
new candidates add rows here rather than editing the rules above.

| rule | scope | what it does instead | why | status |
|---|---|---|---|---|
| §4 square corners | `[panel]` | menus/tooltips `radius: 3`, text entries `radius: 2` | a menu chip and an entry box do not read as *windows*; the rule is about window-like surfaces. **The only two rounding values on the desktop** | [code] |
| §3.1 the wallpaper owns the palette | `[panel]` | `BG` is hardcoded `000000` and never derived; `windowBorderInactive` is a static `595959aa` | pure black is the shared floor across Qt/kitty/panel (§3.1); a border that must read against *any* wallpaper cannot be a near-neighbour of accent (§3.2) | [code] |
| §3.1 nothing picks a colour | global | an indicator required to read against any wallpaper may take a static colour | measured: every wal slot is within 1.5:1 of accent, so a themed indicator has no contrast left (§3.2, `7628fed`) | [code] |
| §6.2 one motion vocabulary | global | physics-driven indicators use a gravity model and the peak marker carries **no** `Behavior` at all | "the velocity term is what makes a peak read as falling rather than fading"; easing over 60fps data is a second low-pass (§6.9) | [code] |
| §6.8 every window uses the desktop's open/close animation | `[hyprland]` | `monitorAdded` entrance animation is disabled | "the desktop should just BE there" — no login animation (§6.8) | [code] |
| §9.2 momentum belongs to the compositor | global | discrete steppers (volume, brightness, tray) stay notch-based via `WheelNotch` | they are steppers, not scroll surfaces; "a coast that walks brightness to 0 is a bug" (§9.2) | [his] |
| §12.1 a pressed cell inverts for 220ms | `[hyprvtb]` | close and minimize show no flash | their result is instantly visible, so the confirmation is redundant (§12.1) | [code] |
| §8 every button gets a tooltip | `[hyprvtb]` | tooltips are suppressed on unfocused windows | "the cursor is usually just passing over it to click-focus" (`737dce7`) | [code] |
| §2.3 foreign text is mapped at ingest | global | identifying strings — paths, pids, argv, task titles — and **prefill sites** (rename dialog, drive-label editor) are never mapped | mapping them renames the user's file or relabels their volume (§2.3) | [code] |
| §2.2 no bold, ever | global | emphasis is carried by colour and position instead | the font ships Regular only; synthetic bold "reads as a different typeface" (`7da096d`) | [code] |
| §6.1 reload must be undetectable | `[panel]` | `ViewMode.slowmo` is deliberately **not** persisted and **not** a settings key | so a reload always restores 1x and it cannot be left on by accident (§6.10) | [code] |
| §16 the desktop's idiom applies to everything drawn | `[surfer]` | the desktop's *font family* is imposed on a page; its sizes and palette are not, and the choice is per-site | forcing size and palette is reader-mode territory and breaks real sites — a full reskin was built and explicitly retracted (`ad868e4`) | [his] |
| §5.1 zero-gap, edge-to-edge | global | an interactive target never touches its neighbour, and its hit band may exceed its ink | he reported the queue's collapse handle as unclickable at `gap = 0` (§5.3) | [his] |
| §18 the dock shows the system's tiles | `[panel]` | the disk tile is classic-mode only | by choice (§18) | [his] |
| §6.1 nothing on screen loads asynchronously | `[panel]` | `MediaContent`'s cover art (`asynchronous`+`cache`, over a placeholder) and `TaskCell`'s lazy `DesktopEntries` scan (over a letter fallback) still load async | **under review.** Both were inspected during `79e9dea` and deliberately left: neither can produce an empty frame, because each draws over something, and neither was changed without measuring first | candidate |
| §8 one tooltip dwell | `[hyprvtb]` | 450ms, against the panel's 350ms | **unruled.** The titlebar is a place the cursor passes through more often, so a longer dwell *may* be deliberate — nothing records it as such (Open question 4) | candidate |
| §2.1/§2.2 a text row is exactly one font cell, `lineHeight` pinned under `FixedHeight` | `[painter]` | the prompt `TextEdit` leads at Qt's rounded 16px | **impossible, not a choice:** `lineHeight`/`lineHeightMode` are `Text`-only properties. Assigning them to a `TextEdit` is a component-creation *error* — `21534ca` did, and painter could not load its QML at all until it was removed. The one multi-line editor in the tree | [code] |
| §5.4 the lyrics box is one presentation in two trees | `[panel]` | the panel's copy drops the pane's `lyrics · <source>` header and its "mark instrumental" control | §5.4's own rule: in a five-row drawer the header costs a fifth of the box to name what it obviously is, and marking a track instrumental needs the library the panel does not have | [code] |
| §5.4 widget titles come off; the content identifies itself | `[painter]` | the left column's `Panel` boxes keep section titles (`model`, `prompt`, `sampling`, `resolution`, `patches`, `lora`) | **unruled.** They are *collapsible* boxes: collapsed to a header, a box with no title is unidentifiable, and the title is also the click target. §5.4's evidence is all about non-collapsible widgets (Open question 10) | candidate |

---

## Open questions

Agent *proposals*, listed separately on purpose. Nothing above depends on them.

1. ~~Should the apps read the panel's font size instead of hardcoding 15?~~
   **Done** — see §2.7. (Parsing the panel's `Theme.qml` for it, as this entry
   proposed, would not have worked: the palette is written there as literals,
   but `font`/`fontSize` are QML expressions only Quickshell can evaluate.)
2. **Should `Glyphs.px()` be shared with the apps?** You asked for it to be
   wired "through the others" in the panel; the apps have the same problem and
   no mapping at all. Doing it means a `qmlcommon/` or `pylib/` copy of the
   table, with the panel's as canonical.
3. **Should the byte-identical duplicates move into `apps/qmlcommon/`?**
   `Theme.qml` (6), `PixelText.qml` (6), `VScroll.qml` (2), `CtxMenu.qml` (2).
   Counter-argument: the theme is per-app deliberately, because it is installed
   as a *context property*.
4. **One tooltip dwell, or two on purpose?** 350ms panel vs 450ms titlebar. The
   titlebar is a place the cursor passes through more often, so the longer dwell
   may be deliberate — nothing records it as such.
5. **Normalise `player`'s two odd timings** to 220ms `OutCubic`
   (`SettingsPanel` 200ms, `AlbumGrid` 130ms `OutQuad`), or is the album panel
   deliberately snappier?
6. **Is there a rule about ICONS?** This file covers text, colour, motion,
   layout and glyphs, but the icon story (tray, dock tiles, task cells,
   `.desktop` icons) is written down nowhere. §12.1 says *controls* are pixel
   glyphs; app identity icons are a different question.
7. **Should the sound set ever grow?** §17 records a deliberate narrowing. Is
   "no new sounds without asking" the rule, or is the current set simply where
   it stopped?
8. ~~**A shared `Theme.animDuration`?**~~ **Done**, and the answer turned out
   not to be a theme property at all: the duration lives in the compositor, as
   `plugin:hyprvtb:slide_duration_ms`, because the roll is the reference and the
   reference should not be a copy of itself. The panel takes it through
   `ViewMode.slideMs`/`ms()` and the apps through `qmlcommon/Motion.qml`; both
   settings are live. §6.2. The last loose end is closed too:
   `pylib/deskstyle.py` now publishes `reduceMotion`/`animSpeed` alongside
   `fontFamily`/`fontSize`, so the two Settings > Appearance controls that had
   moved only the panel now scale every animation in all six apps as well —
   verified offscreen at 0.5x/1.5x/2.0x and at `reduceMotion`, through the real
   `Motion.qml`.
9. **The five other dead settings** (`themeMode`, `accentOverride`,
   `paletteColorCount`, `pureBlackBg`, and whichever of the above survives):
   wire them, or remove the controls? §10 says a control that is drawn is a
   control that works, so leaving them visible is the one option that is
   definitely wrong.
10. ~~**Bring painter into line?**~~ **Done** — all eight in one pass; §19.1
    records what each became. Two things it left standing, deliberately, and
    which want a ruling: painter's `Panel` boxes still carry **section titles**
    (`model`, `prompt`, `sampling`, ...) where §5.4 says widget titles come off
    and the content identifies itself — but a collapsed box with no title is
    unidentifiable, so this may be a case §5.4 should exempt rather than a
    divergence to fix. And a **`Spin` is a discrete stepper**, so it went to
    `WheelNotch` rather than `WheelScroll`: one classic detent is still exactly
    one step, but the touchpad now moves a value every ~10px of finger travel
    (the panel's stepper unit) where painter's hand-rolled version wanted 40px.
11. **Sweep the non-ASCII titlebar labels?** viewer's `‖ ▶ ‹ › − ×` and filer's
    `↑`/`↓` are drawn by the plugin in a font that lacks them. The panel was
    swept for this once (`48a6ff3`); the apps never were.

---

## Maintaining this file

1. **Rule first, story second.** Lead with the instruction; keep the incident
   that produced it as the supporting clause. Every prohibition here was paid
   for once already, and the provenance is what stops the fix being "improved"
   back out.
2. **Mark provenance, and never smuggle taste in as his decision.** `[his]` for
   a stated decision — quote him verbatim, typos included, because the wording
   is the evidence. `[code]` for a promoted convention. Anything you merely
   think would be better goes in **Open questions**.
3. **Detail belongs at the right level.** This file is the cross-cutting look
   and feel. How a widget is wired, what crashes it, and how to get it live
   belong in that area's `AGENTS.md`. Link, don't duplicate.
4. **When you change how something looks, change this file in the same commit** —
   otherwise the next agent restores the old look from here.
5. **When he states a preference in a session, it belongs here** — that is the
   entire point. A rule he has had to say twice is a bug in this document.
6. **Write the scope down at the same time (§0).** A new rule is global unless
   you tag it; a new *divergence* is a row in §20 in the same commit, or it is
   a bug. A rule he has had to widen from one program to the desktop is the
   same bug as one he has had to say twice.
