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
    // `wallpaperFit` (Settings > Appearance) overrides that decision: "auto"
    // takes wal-prepare.sh's, "tile"/"scale" force one. Applied HERE rather than
    // by passing WAL_MODE into wal-prepare.sh, because the mode is cached PER
    // IMAGE — forcing it there would need every image's cache invalidated and
    // would still leave the published file disagreeing with the setting. As a
    // binding it also applies the instant the toggle moves, with no re-apply.
    readonly property string mode: {
        const f = SettingsStore.d.wallpaperFit;
        if (f === "tile" || f === "scale") return f;
        return _mode === "tile" ? "tile" : "scale";
    }

    property string _path: ""
    property string _mode: "scale"
    property string _blur: ""

    // The clusters wal-extract.py quantised the current wallpaper into —
    // bare rrggbb, dominant first, dropped ones included — published by
    // wal-set.sh to current.clusters. Drawn by the Settings swatch row
    // (SetSwatches.qml); empty until the first theme apply writes the file.
    property var clusters: []
    function _setClusters(t) {
        const s = (t || "").trim();
        root.clusters = s.length ? s.split(",") : [];
    }

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

    // The visible frame's load state at the END of the tree's own completion —
    // i.e. what the FIRST frame of a reload will be painted with. This is the
    // regression check for the reload flash: anything but "ready" means the
    // panel commits a frame with no wallpaper in it and the screen flashes
    // Theme.bg. It stays whatever the last completed tree recorded, so it is
    // readable long after the reload.
    property string firstPaint: "?"

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

    FileView {
        id: clustersFile
        path: root.cacheDir + "/current.clusters"
        watchChanges: true
        blockLoading: true
        printErrors: false
        onTextChanged: root._setClusters(text())
        onLoaded: root._setClusters(text())
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
        onTriggered: { curFile.reload(); modeFile.reload(); blurFile.reload(); clustersFile.reload(); }
    }

    // Read all three files RIGHT NOW, synchronously, and return the path.
    //
    // A SINGLETON'S OWN COMPONENT COMPLETION IS AT THE END OF THE LOAD PASS, so
    // a consumer's Component.onCompleted reads `url` before these FileViews have
    // ever loaded — `blockLoading` does not help, because the blocking load is
    // what completion triggers. Measured on a forced reload: WallpaperLayer's
    // onCompleted saw `Wall.url.length === 0`, and the real value only arrived
    // 20 ms later, i.e. after the pass. So the wallpaper was assigned its source
    // too late to be on the reload's first frame.
    //
    // Same shape, and the same reason, as SettingsStore.loadNow(): the reload()
    // is not enough on its own, reading text() is what forces the read to
    // complete. Call this first in any one-shot handler that needs the wallpaper.
    function loadNow(): string {
        curFile.reload();  root._path = curFile.text().trim();
        modeFile.reload(); root._mode = modeFile.text().trim();
        blurFile.reload(); root._blur = blurFile.text().trim();
        return root._path;
    }
}
