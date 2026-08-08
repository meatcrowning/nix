import QtQuick

// One widget in the dock's grid: a framed rectangle of cells, with a content
// component inside it.
//
// The content is loaded by FILE NAME rather than instantiated directly, so the
// grid's layout is plain data (see DockGrid.qml's PLACEMENTS) — which is what
// phase 3 needs in order to let the user move and resize these, and to persist
// where they put them. It also means a tile that is scrolled far off the bottom
// of a long grid has cost nothing until it is asked for.
//
// `active` is forwarded into the content through a Binding rather than assigned
// once, because the Loader creates the item asynchronously with respect to this
// property: a plain assignment in onLoaded would capture whatever the value
// happened to be at that instant, and the content would keep polling after the
// dock was closed.
Item {
    id: root

    property string source: ""
    property string tileKey: ""
    property bool active: true
    // The content's height in this tile's closed (no queue rows) configuration,
    // set by the grid. Forwarded to the content so a widget whose drawer shrinks
    // its own row span (the player's queue) can keep its top section fixed.
    // -1 means "not a grid tile / no closed form" and the content carries on.
    property real gridClosedH: -1

    // Publish allotted-vs-wanted for `qs ipc call live tiles`. "No blank space"
    // is a number, not an opinion, and this is where it can be read.
    // A tile that changes ROW — the player's queue drawer taking rows off the
    // forecast — glides there. Only y and height: x and width follow the panel
    // edge during a resize drag, and animating anything that tracks the pointer
    // is the one thing this panel does not do (see the LAW in AGENTS.md). The
    // drag gate covers the case where a mode switch changes both at once.
    // ViewMode.settling covers the reload: the grid is laid out before the panel
    // knows its real width, so without it every tile glides into place from
    // wherever the default-classic geometry put it, on every theme change.
    //
    // `ViewMode.slideMs`/`slideEasing` are the DESKTOP'S CANONICAL SLIDE (260ms,
    // OutCubic — hyprvtb's window roll), not a number picked for this file. The
    // wallpaper glide and SlidePopup's fan already ran at 260; these tiles were
    // the outlier at 200, which is what made the player's queue drawer visibly
    // quicker than a window rolling out beside it — and the queue drawer has no
    // animation of its own, so THIS Behavior is the drawer's slide.
    Behavior on y {
        enabled: !ViewMode.dragging && !ViewMode.settling
        NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
    }
    Behavior on height {
        enabled: !ViewMode.dragging && !ViewMode.settling
        NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
    }

    // The grid's generation, so ViewMode can tell this panel's numbers from
    // those of the one a reload is in the middle of replacing. Reporting again
    // when it lands matters: the delegates complete BEFORE the grid does, so the
    // first reports go out stamped 0 and are dropped.
    property int gen: 0
    onGenChanged: report()

    readonly property real contentHeight: loader.item ? loader.item.implicitHeight : -1
    function report() { ViewMode.reportTile(tileKey, height, contentHeight, gen); }
    onContentHeightChanged: report()
    onHeightChanged: report()

    // The frame. Deliberately quieter than a popup card's: these sit inside the
    // panel, against its own background, not out on the wallpaper.
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: Theme.ctrlBorder
        border.color: Theme.border
        radius: Theme.windowRounding
    }

    // Whether this tile has its widget in it. DockGrid reads it at completion:
    // a tile that is not ready when the tree completes is a tile the reload's
    // first frame paints as an empty frame.
    readonly property bool ready: loader.status === Loader.Ready

    // SYNCHRONOUS, and that is the whole reason the panel no longer flashes
    // black on a reload.
    //
    // A reload hands the bar's layer surface over still mapped, so the
    // compositor keeps showing the OLD buffer until the new tree paints — and
    // an asynchronous Loader cannot have its widget in that first frame. Every
    // tile came up as this Rectangle's 1px border over Theme.bg, i.e. the whole
    // dock as empty outlines, on every theme, wallpaper or agent hot reload.
    // Measured with a `Date.now()` warn on Loader.onStatusChanged across one
    // forced reload, in dock mode at 378px:
    //
    //     t+0  ms   status = Loading  for all five tiles
    //     t+0  ms   Configuration Loaded            <- the tree is up and will paint
    //     t+82..95  status = Ready    tasks, clock, calendar, weather, media
    //
    // Blocking here spends that time INSIDE the load pass, where the old frame
    // is still on screen and nothing is animating, which is the same trade the
    // wallpaper's first paint makes (WallpaperImage.loadNow, efccc34).
    //
    // The laziness this gives up was already notional: DockGrid is ONE PAGE
    // with no scrolling, so every tile in `placements` is on screen at all
    // times and gets built either way — asynchronously only meant "later", not
    // "only if needed". The `active` Binding below is unaffected and must stay:
    // it is about the property arriving late, not the item.
    Loader {
        id: loader
        anchors.fill: parent
        anchors.margins: 1
        clip: true
        asynchronous: false
        source: root.source
    }

    Binding {
        target: loader.item
        property: "active"
        value: root.active
        when: loader.item !== null
    }
    Binding {
        target: loader.item
        property: "gridClosedH"
        value: root.gridClosedH
        // Only forward to a content that actually declares the property — the
        // other dock widgets do not, and setting an unknown property on them is
        // a warning per tile into the cumulative `qs log`.
        when: loader.item !== null && loader.item.gridClosedH !== undefined
    }
}
