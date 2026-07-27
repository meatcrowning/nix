pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// WHICH wallpaper is current, and how it should be laid out. The drawing itself
// is WallpaperLayer.qml.
//
// The panel draws the wallpaper because hyprpaper no longer does. Two reasons it
// had to go: it re-rendered its whole background layer surface on every set,
// which reads on screen as the wallpaper FLASHING (wal-set.sh went out of its
// way to skip redundant sets purely to avoid it), and it had no notion of an
// OFFSET — so centring the art in the non-panel region meant compositing a
// whole new full-screen image with ImageMagick for every panel width, then
// setting it, then flashing. Drawing it here makes the recentre a property
// binding that animates with the panel edge, and a wallpaper change a
// cross-fade.
//
// wal-set.sh is still the thing that DECIDES the wallpaper (and owns the
// palette extraction, kitty, cursors, OpenRGB). It now just publishes its
// choice to two files instead of driving a wallpaper daemon.
Singleton {
    id: root

    readonly property string cacheDir:
        (Quickshell.env("HOME") || "/home/lam") + "/.cache/wal"

    // Absolute path of the current wallpaper, and "tile" | "scale" — the
    // decision wal-prepare.sh makes from the image's own dimensions (a small,
    // roughly-square image is a repeating texture; anything else is a photo).
    readonly property string path: _path
    readonly property string mode: _mode === "tile" ? "tile" : "scale"

    property string _path: ""
    property string _mode: "scale"
    property string _blur: ""

    // The pre-blurred backdrop wal-prepare.sh cached for this image. Empty until
    // it exists; WallpaperLayer falls back to blurring the source itself, so a
    // missing file is a quality regression for one wallpaper, never a black gap.
    readonly property string blurUrl: _blur.length ? "file://" + _blur : ""

    // Diagnostics, published by WallpaperLayer and read with
    // `qs ipc call wallpaper status`. There is no other way to confirm from
    // outside that the image actually DECODED rather than silently failing to a
    // flat background — and that mattered a great deal at the point hyprpaper
    // was switched off, since a blank desktop would have been the alternative.
    property string frontStatus: "none"
    property string frontUrl: ""

    // A file:// URL for Image.source. Empty stays empty so the Image simply
    // doesn't load rather than erroring on a malformed URL.
    readonly property string url: _path.length ? "file://" + _path : ""

    FileView {
        id: curFile
        path: root.cacheDir + "/current"
        watchChanges: true
        blockLoading: true
        printErrors: false          // absent before wal-set.sh has ever run
        onTextChanged: root._path = text().trim()
        onLoaded: root._path = text().trim()
    }

    FileView {
        id: modeFile
        path: root.cacheDir + "/current.mode"
        watchChanges: true
        blockLoading: true
        printErrors: false
        onTextChanged: root._mode = text().trim()
        onLoaded: root._mode = text().trim()
    }

    FileView {
        id: blurFile
        path: root.cacheDir + "/current.blur"
        watchChanges: true
        blockLoading: true
        printErrors: false
        onTextChanged: root._blur = text().trim()
        onLoaded: root._blur = text().trim()
    }

    // Fallback poll. watchChanges alone is not quite enough here for the same
    // reason SettingsStore polls: an inotify watch follows the INODE, so any
    // writer that replaces the file (temp + rename) silently detaches it.
    // wal-set.sh writes these two in place specifically to avoid that, but the
    // wallpaper picker previews by re-running wal-set.sh on every arrow key, and
    // a preview that misses is very visible. Two tiny reads twice a second is
    // nothing next to that.
    Timer {
        interval: 500
        running: true
        repeat: true
        onTriggered: { curFile.reload(); modeFile.reload(); blurFile.reload(); }
    }
}
