#!/usr/bin/env python3
"""booru -- a booru browser: search posts, read their tags, follow them.

Revived from cte's Danbooru browser (painter's predecessor on top) as its own
program. The client is booruapi.py; this file is the Qt side: worker threads,
an image provider that fetches with booru's own User-Agent (Danbooru's CDN
refuses Qt's), and the `Booru` context property the QML drives.

Two roofs, one tree, as in coder: under Plasma qml/Root.qml sits in a kdeshell
QMainWindow with native menus and toolbar; under Hyprland qml/Main.qml is a
Window around it and the hyprvtb titlebar carries the buttons.

  booru [QUERY] [--site=danbooru] [--selftest] [--face=plasma|hypr]
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"
sys.path.insert(0, str(HERE.parent / "pylib"))
sys.path.insert(0, str(HERE))

VERSION = "0.1"

selftest = "--selftest" in sys.argv
if selftest:
    sys.argv.remove("--selftest")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("DISPLAY", None)
face = ""
start_site = ""
for _arg in list(sys.argv[1:]):
    if _arg.startswith("--face="):
        face = _arg.split("=", 1)[1]
        sys.argv.remove(_arg)
    elif _arg.startswith("--site="):
        start_site = _arg.split("=", 1)[1]
        sys.argv.remove(_arg)
if face == "hypr":
    os.environ["DESK_SESSION"] = "hypr"
elif face == "plasma":
    os.environ["DESK_SESSION"] = "plasma"
start_query = " ".join(a for a in sys.argv[1:] if not a.startswith("-"))

from PySide6.QtCore import (QObject, Property, QRunnable, QSize, QThreadPool,  # noqa: E402
                            QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QColor, QGuiApplication, QImage, QImageReader  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402
from PySide6.QtQuick import (QQuickAsyncImageProvider, QQuickImageResponse,  # noqa: E402
                             QQuickTextureFactory, QQuickWindow)  # noqa: F401

import booruapi as api  # noqa: E402
import boorutags  # noqa: E402
import kdeshell  # noqa: E402
from deskstyle import DeskStyle  # noqa: E402
from kdetheme import is_plasma, theme_source  # noqa: E402
from nativepalette import session_palette  # noqa: E402
from styleparticipant import StyleParticipant  # noqa: E402

try:
    from vtbclient import VtbClient  # noqa: E402
except Exception:  # noqa: BLE001
    VtbClient = None

STATE_PATH = (Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
              / "booru" / "state.json")
SAVE_DIR = Path(os.environ.get("BOORU_SAVE_DIR", Path.home() / "Pictures" / "booru"))

PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


@session_palette
class Palette(QObject):
    """The wallpaper palette (Hyprland face); Plasma forwards native roles."""
    changed = Signal()

    def __init__(self, path, parent=None):
        from PySide6.QtCore import QFileSystemWatcher
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        directory = os.path.dirname(self._path)
        if os.path.isdir(directory):
            self._watcher.addPath(directory)
        self._rewatch()
        self._load()

    def _rewatch(self):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return False
        colors = dict(self._colors)
        parsed = False
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            if m.group(1) in PALETTE_KEYS:
                colors[m.group(1)] = m.group(2)
                parsed = True
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()
        return parsed

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    from PySide6.QtCore import Property as _P
    bg = _P(QColor, lambda s: s._c("bg"), notify=changed)
    bgAlt = _P(QColor, lambda s: s._c("bgAlt"), notify=changed)
    border = _P(QColor, lambda s: s._c("border"), notify=changed)
    accent = _P(QColor, lambda s: s._c("accent"), notify=changed)
    dim = _P(QColor, lambda s: s._c("dim"), notify=changed)
    text = _P(QColor, lambda s: s._c("text"), notify=changed)
    textDim = _P(QColor, lambda s: s._c("textDim"), notify=changed)
    highlight = _P(QColor, lambda s: s._c("highlight"), notify=changed)
    ok = _P(QColor, lambda s: s._c("ok"), notify=changed)
    warn = _P(QColor, lambda s: s._c("warn"), notify=changed)
    crit = _P(QColor, lambda s: s._c("crit"), notify=changed)
    info = _P(QColor, lambda s: s._c("info"), notify=changed)
    del _P


class Titlebar(QObject):
    """hyprvtb buttons for the Hyprland face; inert under Plasma."""
    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        if VtbClient is not None and not is_plasma() and not selftest:
            try:
                self._client = VtbClient(on_click=self.clicked.emit)
            except Exception:  # noqa: BLE001 - outside hyprvtb is fine
                self._client = None

    @Slot("QVariantList")
    def setButtons(self, buttons):
        if not self._client:
            return
        out = []
        for b in buttons:
            if hasattr(b, "toVariant"):
                b = b.toVariant()
            if isinstance(b, str):
                out.append("-")
            else:
                out.append((str(b["id"]), str(b["label"]), int(b.get("state", 0)),
                            str(b.get("tip", "")), False, bool(b.get("bottom", False))))
        try:
            self._client.set_buttons(out)
        except Exception:  # noqa: BLE001
            pass

    @Slot(str)
    def setFooter(self, text):
        if self._client:
            try:
                self._client.set_footer(text)
            except Exception:  # noqa: BLE001
                pass


# ---- images -----------------------------------------------------------------

class _Response(QQuickImageResponse, QRunnable):
    """One `image://booru/<url>`: fetched (or read from the disk cache) and
    decoded on the pool, scaled to the requested size."""

    def __init__(self, url, size):
        QQuickImageResponse.__init__(self)
        QRunnable.__init__(self)
        self.setAutoDelete(False)
        self._url = url
        self._size = size
        self._image = QImage()
        self._error = ""

    def run(self):
        try:
            path = api.cached(self._url)
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            if self._size.isValid() and self._size.width() > 0 and self._size.height() > 0:
                full = reader.size()
                if full.isValid() and (full.width() > self._size.width()
                                       or full.height() > self._size.height()):
                    reader.setScaledSize(full.scaled(self._size, _KEEP))
            self._image = reader.read()
            if self._image.isNull():
                self._error = reader.errorString() or "could not decode"
        except Exception as e:  # noqa: BLE001
            self._error = str(e) or "fetch failed"
        self.finished.emit()

    def textureFactory(self):
        return QQuickTextureFactory.textureFactoryForImage(self._image)

    def errorString(self):
        return self._error


from PySide6.QtCore import Qt  # noqa: E402
_KEEP = Qt.KeepAspectRatio


class ImageProvider(QQuickAsyncImageProvider):
    def __init__(self):
        super().__init__()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(6)

    def requestImageResponse(self, image_id, requested_size):
        # The id is the percent-ENCODED url (Root.qml `img()`), so a `?` or `#`
        # in it reaches here instead of being eaten by the image:// URL.
        url = QUrl.fromPercentEncoding(image_id.encode("utf-8"))
        resp = _Response(url, requested_size)
        # The post being looked at (no sourceSize) jumps the queue of
        # thumbnails, or opening a post mid-scroll waits behind a page of them.
        full = not (requested_size.isValid() and requested_size.width() > 0)
        self._pool.start(resp, 10 if full else 0)
        return resp


# ---- the Booru context property ------------------------------------------------

def _dtext_plain(body):
    """Danbooru DText as PLAIN text (docs/DESIGN.md 2.6) plus its link targets.

    `[[target|label]]` reads as `label`; the targets come back separately and
    the QML draws them as tag buttons, so following a link never needs a markup
    renderer."""
    links = []

    def link(m):
        target, _, label = m.group(1).partition("|")
        t = target.strip().lower().replace(" ", "_")
        if t and t not in links and not t.startswith(("help:", "howto:", "about:")):
            links.append(t)
        return (label or target).strip()

    text = re.sub(r"\[\[([^\]]+)\]\]", link, body or "")
    text = re.sub(r"\{\{([^}]+)\}\}", lambda m: m.group(1), text)
    text = re.sub(r'"([^"]+)":\[?(?:https?://|/)\S+?\]?(?=\s|$)', r"\1", text)
    text = re.sub(r"\[/?(?:b|i|u|s|tn|spoilers?|code|quote|expand[^\]]*|table|tr|td|th|"
                  r"thead|tbody|nodtext|url[^\]]*)\]", "", text, flags=re.I)
    text = re.sub(r"^h[1-6](?:#\S+)?\.\s*", "", text, flags=re.M)
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, links


def _prompt_tag(t):
    """A tag the way a prompt is written: spaces, not underscores — except in
    an emoticon (`^_^`), where the underscore IS the tag."""
    return t if re.fullmatch(r"[\W_]+", t) else t.replace("_", " ")


class Booru(QObject):
    postsReady = Signal(int, "QVariantList", int, int, bool)   # gen, posts, total, page, last
    failed = Signal(int, str)
    wikiReady = Signal(str, str, str, "QVariantList")           # tag, title, text, links
    relatedReady = Signal(str, "QVariantList")
    mediaReady = Signal(str, str)                               # url, file url
    mediaFailed = Signal(str, str)
    toast = Signal(str, str)
    busyChanged = Signal()
    tagsReadyChanged = Signal()

    PAGE = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gen = 0
        self._req = None
        self._page = 0
        self._last = False
        self._loading = False
        self._index_job = None
        threading.Thread(target=api.prune_cache, daemon=True).start()

    # -- plumbing
    def _bg(self, fn, *a):
        threading.Thread(target=fn, args=a, daemon=True).start()

    def _set_loading(self, on):
        if on != self._loading:
            self._loading = on
            self.busyChanged.emit()

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._loading

    @Property("QVariantList", constant=True)
    def sites(self):
        return [{"id": k, "label": v["label"], "caps": sorted(v["caps"]),
                 "key": v["key"], "hasKey": bool(api.credentials(k).get("api_key"))}
                for k, v in api.SITES.items()]

    # -- posts
    @Slot(str, str, str, str, result=int)
    def search(self, site, query, rating, order):
        if site not in api.SITES:
            site = "danbooru"
        self._gen += 1
        self._req = (site, query.strip(), rating, order)
        self._page = 0
        self._last = False
        self._fetch_page()
        return self._gen

    @Slot(result=bool)
    def more(self):
        if self._req is None or self._last or self._loading:
            return False
        self._fetch_page()
        return True

    def _fetch_page(self):
        gen, page = self._gen, self._page + 1
        site, q, rating, order = self._req
        self._set_loading(True)

        def work():
            try:
                r = api.search_posts(site, q, page=page, limit=self.PAGE,
                                     rating=rating, order=order)
            except api.BooruError as e:
                msg = str(e)
                if "more than 2 tags" in msg and site == "danbooru":
                    msg = ("danbooru takes 2 tags without an account; add login and "
                           "api_key to ~/.config/booru/danbooru.json")
                self._done_fail(gen, f"{api.SITES[site]['label'].lower()}: {msg[:1].lower()}{msg[1:]}")
                return
            except Exception as e:  # noqa: BLE001
                self._done_fail(gen, str(e))
                return
            self._done_page(gen, page, r)

        self._bg(work)

    def _done_page(self, gen, page, r):
        if gen != self._gen:
            return
        self._page = page
        self._last = len(r["posts"]) == 0
        self._loading = False
        self.busyChanged.emit()
        total = r["total"] if r["total"] is not None else -1
        self.postsReady.emit(gen, r["posts"], total, page, self._last)

    def _done_fail(self, gen, msg):
        if gen != self._gen:
            return
        self._loading = False
        self.busyChanged.emit()
        self.failed.emit(gen, msg)

    # -- tag lookups
    @Slot(str, str)
    def wiki(self, site, tag):
        def work():
            try:
                w = api.wiki(site, tag)
            except api.BooruError as e:
                self.wikiReady.emit(tag, tag, "wiki: " + str(e), [])
                return
            text, links = _dtext_plain(w["body"])
            self.wikiReady.emit(tag, w["title"], text, links)
        self._bg(work)

    @Slot(str, str, str)
    def related(self, site, tag, category):
        def work():
            try:
                rows = api.related(site, tag, category)
            except api.BooruError:
                rows = []
            self.relatedReady.emit(tag, rows)
        self._bg(work)

    @Slot(str, result="QVariant")
    def tagInfo(self, tag):
        e = boorutags.resolve(tag)
        return e or {}

    # -- media: GIFs and video play from the disk cache, not the network
    @Slot(str)
    def media(self, url):
        def work():
            try:
                p = api.cached(url)
            except Exception as e:  # noqa: BLE001
                self.mediaFailed.emit(url, str(e))
                return
            self.mediaReady.emit(url, QUrl.fromLocalFile(str(p)).toString())
        self._bg(work)

    # -- completer (pylib/boorutags; painter's Tags, without the prompt spelling)
    @Property(bool, notify=tagsReadyChanged)
    def tagsReady(self):
        return boorutags.index_ready()

    @Slot()
    def prepareTags(self):
        if self._index_job is not None or boorutags.index_ready() \
                or not os.path.exists(boorutags.DATA):
            return

        def work():
            try:
                boorutags.build_index()
            except Exception:  # noqa: BLE001 - no completions is never a crash
                pass
            self.tagsReadyChanged.emit()
        self._index_job = threading.Thread(target=work, daemon=True)
        self._index_job.start()

    @Slot(str, int, result="QVariantList")
    def complete(self, fragment, limit=8):
        neg = fragment.startswith("-")
        q = fragment.lstrip("-").strip()
        if not q or not boorutags.index_ready():
            self.prepareTags()
            return []
        norm = q.lower().replace(" ", "_")
        found = (boorutags.search(q, limit=limit, order="posts")
                 or boorutags.loose(q, limit=limit))
        out = []
        for e in found:
            alias = ""
            if norm not in e["tag"]:
                alias = next((a for a in e["aliases"] if norm in a), "")
            out.append({"tag": e["tag"], "category": e["category"], "posts": e["posts"],
                        "alias": alias, "insert": ("-" if neg else "") + e["tag"]})
        return out

    # -- out of the app
    @Slot(str)
    def copyText(self, text):
        QGuiApplication.clipboard().setText(text)
        self.toast.emit("copied", "ok")

    @Slot("QVariantList", result=str)
    def promptText(self, tags):
        return ", ".join(_prompt_tag(str(t)) for t in tags)

    @Slot("QVariant")
    def save(self, post):
        post = post.toVariant() if hasattr(post, "toVariant") else dict(post)

        def work():
            try:
                src = api.cached(post["original"])
            except Exception as e:  # noqa: BLE001
                self.toast.emit("save failed: " + str(e), "crit")
                return
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            dst = SAVE_DIR / f"{post['site']}-{post['id']}.{post['ext'] or src.suffix.lstrip('.')}"
            shutil.copyfile(src, dst)
            self.toast.emit("saved " + str(dst).replace(str(Path.home()), "~"), "ok")
        self._bg(work)

    @Slot("QVariant")
    def openViewer(self, post):
        post = post.toVariant() if hasattr(post, "toVariant") else dict(post)

        def work():
            try:
                src = api.cached(post["original"])
            except Exception as e:  # noqa: BLE001
                self.toast.emit("open failed: " + str(e), "crit")
                return
            viewer = shutil.which("viewer") or shutil.which("xdg-open")
            if not viewer:
                self.toast.emit("no viewer on PATH", "crit")
                return
            subprocess.Popen([viewer, str(src)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        self._bg(work)


class Settings(QObject):
    """booru's own persisted state, ~/.config/booru/state.json."""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self._data = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            self._data = {}

    @Slot(str, "QVariant", result="QVariant")
    def get(self, key, default=None):
        return self._data.get(key, default)

    @Slot(str, "QVariant")
    def set(self, key, val):
        if hasattr(val, "toVariant"):
            val = val.toVariant()
        self._data[key] = val
        if selftest:
            return
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data), encoding="utf-8")
            os.replace(tmp, STATE_PATH)
        except OSError:
            pass


def main():
    if face == "hypr":
        os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
    else:
        kdeshell.pin_controls_style()
    app = kdeshell.make_app(sys.argv, "booru")
    if selftest and app.platformName() != "offscreen":
        raise SystemExit("selftest refuses to run on platform %r" % app.platformName())
    app.setApplicationName("booru")
    app.setApplicationDisplayName("Booru")
    app.setDesktopFileName("booru")

    palette = Palette(theme_source(PANEL_THEME))
    style_participant = StyleParticipant("booru", palette._load, app)  # noqa: F841 keep ref
    style = DeskStyle()
    plasma = is_plasma() if not face else face == "plasma"
    if plasma:
        screen = app.primaryScreen()
        scale = screen.devicePixelRatio() if screen is not None else 1.0
        app.setFont(style.labelFontForScale(scale))

    booru = Booru()
    settings = Settings()
    bar = Titlebar()

    shell = kdeshell.shell("booru", size=(1280, 860), min_size=(560, 420)) if plasma else None
    engine = shell.engine() if plasma else QQmlApplicationEngine()
    if plasma:
        kdeshell.select_plasma_files(engine)
    engine.addImageProvider("booru", ImageProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", bar)
    ctx.setContextProperty("Booru", booru)
    ctx.setContextProperty("Settings", settings)
    ctx.setContextProperty("startQuery", start_query)
    ctx.setContextProperty("startSite", start_site)

    warnings = []
    engine.warnings.connect(lambda errs: warnings.extend(e.toString() for e in errs))

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        return 2
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    if plasma:
        if not shell.load(QML / "Root.qml"):
            for w in shell.errors() + warnings:
                print("  %s" % w, file=sys.stderr)
            return 2
        root = shell.root
        shell.bind_chrome(None)
        shell.bind_status()
        shell.bind_title("windowTitle")
        window = shell.show()
    else:
        engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
        if not engine.rootObjects():
            for w in warnings:
                print("  %s" % w, file=sys.stderr)
            return 2
        window = engine.rootObjects()[0]
        root = window.findChild(QObject, "content")
        bar.clicked.connect(lambda bid: root.tbAction(bid))

    if not selftest:
        from winstate import WinState
        win_state = WinState(window, "booru")  # noqa: F841 keep ref: geometry
        return app.exec()
    return run_selftest(app, shell, window, root, booru, plasma, warnings)


def run_selftest(app, shell, window, root, booru, plasma, warnings):
    """Offscreen only, against BOORU_BASE_URL (tools/booru-test.py serves a
    fixture). BOORU_DRIVE=1 searches, opens the first post and follows a tag;
    BOORU_SHOT writes a PNG; BOORU_MENUS prints the native chrome."""
    from PySide6.QtCore import QEventLoop

    def spin(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def until(cond, ms=8000):
        for _ in range(ms // 50):
            if cond():
                return True
            spin(50)
        return cond()

    def prop(name):
        v = root.property(name)
        return v.toVariant() if hasattr(v, "toVariant") else v

    spin(200)
    report = {"face": "plasma" if plasma else "hypr"}
    if os.environ.get("BOORU_DRIVE"):
        root.setProperty("query", "hatsune_miku")
        root.runSearch(False)
        until(lambda: len(prop("posts")) > 0)
        report["posts"] = len(prop("posts"))
        report["total"] = prop("total")
        root.more()
        until(lambda: prop("pageLoaded") >= 2)
        report["posts_after_more"] = len(prop("posts"))
        root.openPost(0, False)
        spin(400)
        report["post_open"] = prop("postIndex")
        root.showWiki("hatsune_miku")
        until(lambda: prop("wikiTitle") != "" and len(prop("relatedTags")) > 0)
        report["wiki"] = prop("wikiTitle")
        report["wiki_text"] = prop("wikiText")
        report["wiki_links"] = prop("wikiLinks")
        report["related"] = len(prop("relatedTags"))
        report["prompt"] = root.promptFor("general")[:80]
        root.searchTag("long_hair", False)
        spin(300)
        report["query_after_tag"] = prop("query")
        report["post_closed"] = prop("postIndex")
        report["back"] = root.goBack()
        until(lambda: prop("postIndex") == 0)
        report["query_after_back"] = prop("query")
        report["post_after_back"] = prop("postIndex")
        until(lambda: booru.tagsReady, 15000)
        report["completions"] = [c["tag"] for c in booru.complete("hatsu", 3)]
    if os.environ.get("BOORU_SHOT_GRID"):
        root.closePost(True)
        spin(1500)
        img = shell.window.grab().toImage() if plasma else window.grabWindow()
        img.save(os.environ["BOORU_SHOT_GRID"])
    if os.environ.get("BOORU_SHOT"):
        if os.environ.get("BOORU_SHOT_POST") and root.property("postIndex") < 0:
            root.openPost(0, False)
        spin(1200)
        img = shell.window.grab().toImage() if plasma else window.grabWindow()
        img.save(os.environ["BOORU_SHOT"])
        report["shot"] = os.environ["BOORU_SHOT"]
    if plasma and os.environ.get("BOORU_MENUS"):
        report["chrome"] = shell.dump_chrome()
    report["warnings"] = [str(w) for w in warnings]
    print("BOORU_REPORT " + json.dumps(report, default=str))
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
