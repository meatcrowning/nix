"""filer's picker mode — the UI half of the FileChooser portal backend.

`filer --pick <spec.json>` turns the ordinary browser window into a modal file
chooser: the tree, the preview grid, the sort strip and the titlebar address bar
all still work, but a bar appears along the bottom with cancel/accept, the
listing is narrowed to the requested filter, and choosing writes the answer to
the `result` path from the spec and quits.

`portal.py` (same directory) writes the spec and reads the result; its module
docstring has the D-Bus side and explains why this is a subprocess. The contract
between the two is only this file format, so either half can be exercised alone
— which is what makes the picker testable without a bus and the backend testable
without a GUI.

  spec.json   {mode: "open"|"dir"|"save", multiple, title, accept_label,
               current_folder, current_name, filters: [{name, patterns, mimes}],
               current_filter: {name,...}|null, result: "<path>"}
  result.json {uris: ["file:///..."], current_filter: "<filter name>"}

**No result file means "cancelled".** That is the whole error protocol: if this
process dies, is killed by the backend's `Close()`, or the user shuts the window,
the absent file is read as a cancel and the calling app gets a clean response 1
rather than a hung dialog. So `accept()` writes the file and only then quits, and
nothing else ever writes it.
"""
import fnmatch
import json
import mimetypes
import os
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot


def _uri(path):
    """Absolute path -> a percent-encoded file:// URI. The portal spec requires
    every returned URI to have the file:// scheme."""
    return Path(os.path.abspath(path)).as_uri()


class Picker(QObject):
    """Context property `Picker`. Inactive (`active == false`) in a normal filer
    window, and every picker-only branch in Main.qml keys off that — so the
    ordinary browser is exactly what it was."""

    changed = Signal()

    def __init__(self, spec=None, parent=None):
        super().__init__(parent)
        self._spec = spec or {}
        self._done = False
        self._filter = None
        filters = self._spec.get("filters") or []
        want = (self._spec.get("current_filter") or {}).get("name")
        # Honour current_filter when it names one of the offered filters; the
        # spec also allows it standalone with an empty filter list.
        self._filter = next((f for f in filters if f["name"] == want), None)
        if self._filter is None and self._spec.get("current_filter"):
            self._filter = self._spec["current_filter"]
        if self._filter is None and filters:
            self._filter = filters[0]

    # -- state QML reads ------------------------------------------------------

    @Property(bool, constant=True)
    def active(self):
        return bool(self._spec)

    @Property(str, constant=True)
    def mode(self):
        return str(self._spec.get("mode", "open"))

    @Property(bool, constant=True)
    def multiple(self):
        return bool(self._spec.get("multiple", False))

    @Property(str, constant=True)
    def title(self):
        return str(self._spec.get("title") or
                   {"dir": "choose a folder", "save": "save as"}.get(
                       self.mode, "choose a file"))

    @Property(bool, constant=True)
    def saving(self):
        """Save-as: the answer is a name TYPED into the bar, and the file it
        names need not exist. surfer's `<input type=file>` picker asks for this
        mode (Chromium's FileModeSave); the portal backend never does — it
        proxies SaveFile to the gtk/kde delegate, see portal.py."""
        return self.mode == "save"

    @Property(str, constant=True)
    def acceptLabel(self):
        # Mnemonic underlines are allowed in the wire value; strip them, nothing
        # in this UI has mnemonics.
        lbl = str(self._spec.get("accept_label") or "").replace("_", "")
        if lbl:
            return lbl
        return {"dir": "choose", "save": "save"}.get(self.mode, "open")

    @Property(str, constant=True)
    def currentName(self):
        """The name the asking app suggested, which the bar seeds its (editable)
        name box with. Mostly a SaveFile idea, but the spec allows it on an open
        dialog too and it was being dropped on the floor before the box could be
        typed into."""
        return str(self._spec.get("current_name") or "")

    @Property("QVariantList", constant=True)
    def filterNames(self):
        return [f["name"] for f in (self._spec.get("filters") or [])]

    @Property(str, notify=changed)
    def filterName(self):
        return self._filter["name"] if self._filter else ""

    @Slot(str)
    def setFilter(self, name):
        for f in self._spec.get("filters") or []:
            if f["name"] == name:
                self._filter = f
                self.changed.emit()
                return

    # -- filtering ------------------------------------------------------------

    @Slot(str, bool, result=bool)
    def accepts(self, name, is_dir):
        """Should this entry be listed?

        Directories always are — they are how you navigate — and in `dir` mode
        nothing else is. Otherwise a file shows if it matches the active filter;
        with no filter, everything does. Glob patterns are case-sensitive per
        the spec (which is why it tells apps to write `*.[iI][cC][oO]`)."""
        if is_dir:
            return True
        if self.mode == "dir":
            return False
        # Save-as lists files so you can see what a name would land on top of.
        f = self._filter
        if not f:
            return True
        for pat in f.get("patterns") or []:
            if fnmatch.fnmatchcase(name, pat):
                return True
        mimes = f.get("mimes") or []
        if mimes:
            guessed = mimetypes.guess_type(name)[0]
            if guessed:
                for m in mimes:
                    if m == guessed:
                        return True
                    # MIME filters may wildcard the subtype ("image/*").
                    if m.endswith("/*") and guessed.startswith(m[:-1]):
                        return True
        return False

    @Slot(str, result=bool)
    def selectable(self, path):
        """Whether choosing this entry is a valid answer (drives the accept
        button's enabled state). In save mode a click only fills the name box —
        the answer is whatever the box says — so a file is 'selectable' there
        too."""
        is_dir = os.path.isdir(path)
        return is_dir if self.mode == "dir" else not is_dir

    # -- the typed name -------------------------------------------------------
    # The bar's name box is editable, so an answer can be TYPED (or pasted)
    # rather than clicked. Resolving it is python's job for the same reason
    # decoding a uri-list is: QML has no path handling, and the two halves of a
    # "does this name mean anything" question — where it points and what is
    # there — must not be answered in different places.

    @Slot(str, str, result=str)
    def resolvePath(self, text, folder):
        """What the user typed, as an absolute path — `""` for nothing usable.

        `~` and `~user` expand, an absolute path is taken as it stands, and
        anything else is relative to the folder on screen (typing `notes.txt`
        means the one you are looking at). Existence is NOT checked here; that
        is `kindOf`, because "no such file" and "that is a folder" lead to
        different behaviour in the bar."""
        text = str(text).strip()
        if not text:
            return ""
        path = os.path.expanduser(text)
        if not os.path.isabs(path):
            base = str(folder) or os.getcwd()
            path = os.path.join(base, path)
        return os.path.normpath(path)

    @Slot(str, result=bool)
    def writable(self, path):
        """Could something be SAVED at this path? The file need not exist; the
        folder above it must, or the app is handed a path nothing can write."""
        p = str(path)
        return bool(p) and os.path.isdir(os.path.dirname(p) or ".")

    @Slot(str, result=str)
    def kindOf(self, path):
        """`"dir"`, `"file"` or `"missing"` for an absolute path."""
        p = str(path)
        if not p:
            return "missing"
        if os.path.isdir(p):
            return "dir"
        return "file" if os.path.exists(p) else "missing"

    # -- the answer -----------------------------------------------------------

    @Slot("QVariantList")
    def accept(self, paths):
        """Write the result file and quit. Guarded against a second call: the
        result must describe exactly one user decision."""
        if self._done:
            return
        # A save target must NOT have to exist — that is the whole point of one
        # — but its folder must, or nothing can be written there and the app
        # would be handed a path it cannot use.
        keep = ((lambda p: os.path.isdir(os.path.dirname(p) or "."))
                if self.saving else os.path.exists)
        picked = [str(p) for p in paths if keep(str(p))]
        if not picked:
            return
        if not self.multiple:
            picked = picked[:1]
        out = {"uris": [_uri(p) for p in picked]}
        if self._filter:
            out["current_filter"] = self._filter["name"]
        try:
            with open(self._spec["result"], "w", encoding="utf-8") as f:
                json.dump(out, f)
            self._done = True
        except (OSError, KeyError) as e:
            # Leave no result file: the backend reads that as a cancel, which is
            # the safe failure. Never quit pretending we answered.
            print("filer --pick: could not write result:", e)
            return
        self._quit()

    @Slot()
    def cancel(self):
        self._quit()

    def _quit(self):
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.quit()


def load_spec(path):
    """Read a pick spec, or None if it is unusable — in which case filer should
    refuse to start rather than open a browser window the backend will read as a
    cancel only once the user closes it."""
    try:
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, ValueError) as e:
        print("filer --pick: unreadable spec:", e)
        return None
    if not isinstance(spec, dict) or not spec.get("result"):
        print("filer --pick: spec has no result path")
        return None
    spec.setdefault("mode", "open")
    return spec
