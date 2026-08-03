import QtQuick

// The Settings window's scrollbar — the SAME pixel-era idiom the seven Qt apps
// draw (apps/qmlcommon/VScroll.qml, docs/DESIGN.md §9.2), reimplemented here in
// pure QtQuick because the panel imports no QtQuick.Controls. One idiom for the
// whole desktop: win31 / beveled / flat, win31 the default.
//
// It reads the style straight off SettingsStore.d.scrollbarStyle (the same key
// the apps get through DeskStyle), so the control in Settings > Appearance
// updates THIS bar LIVE — a QML binding, no restart. Colours come from the
// panel's own Theme, so it recolours with the wallpaper like everything else.
//
// ALWAYS VISIBLE, no fade (§9.2). Every edge is a 1px Rectangle on an integer
// coordinate; every arrow is GEOMETRY, never a glyph (More Perfect DOS VGA has
// no ▲, §2.3). The bevel is the wallpaper ladder bg < bgAlt < border < dim.
//
// Attach as a SIBLING of the Flickable (not a child — a child scrolls with the
// content) and hand it the flickable. The call site reserves a `barW` gutter so
// the bar sits BESIDE the content, never over it.
Item {
    id: scroll

    // The Flickable this bar drives. Required.
    property Flickable flick

    // ---- which scrollbar -------------------------------------------------
    readonly property string barStyle: {
        const s = SettingsStore.d.scrollbarStyle;
        return (s === "flat" || s === "beveled" || s === "win31") ? s : "win31";
    }
    readonly property bool isWin31: barStyle === "win31"
    readonly property bool isFlat: barStyle === "flat"

    // Read this at the call site that reserves a gutter, never a literal.
    readonly property int barW: isWin31 ? 16 : (barStyle === "beveled" ? 14 : 11)
    readonly property int btn: isWin31 ? barW : 0        // stepper button size

    width: barW

    // The ladder, darkest to lightest — face brighter than the track so a
    // raised thumb does not read as a hole.
    readonly property color dark: Theme.bg
    readonly property color trackC: Theme.bgAlt
    readonly property color face: Theme.border
    readonly property color light: Theme.dim

    // ---- geometry --------------------------------------------------------
    readonly property real _max: flick ? Math.max(0, flick.contentHeight - flick.height) : 0
    readonly property bool _scrollable: _max > 0.5
    readonly property int  _pad: isWin31 ? btn : (isFlat ? 0 : 1)
    readonly property real _avail: Math.max(0, height - 2 * _pad)
    readonly property real _thumbH: _scrollable
        ? Math.max(24, Math.min(_avail, _avail * flick.height / flick.contentHeight))
        : _avail
    readonly property real _thumbY: _pad + (_scrollable ? (_avail - _thumbH) * (flick.contentY / _max) : 0)

    property int stepPx: 48
    function _clampTo(y) { flick.contentY = Math.max(0, Math.min(_max, y)); }

    readonly property bool canUp: _scrollable && flick.contentY > 0.5
    readonly property bool canDown: _scrollable && flick.contentY < _max - 0.5

    // ---- pieces (geometry, no glyphs) ------------------------------------

    // A 1px hard bevel: light top/left + dark bottom/right raised, swapped sunken.
    component Bevel: Item {
        id: bv
        property color faceColor: scroll.face
        property bool sunken: false
        property bool bevelled: !scroll.isFlat
        Rectangle { anchors.fill: parent; color: bv.faceColor }
        Rectangle { visible: bv.bevelled; x: 0; y: 0; width: bv.width; height: 1
                    color: bv.sunken ? scroll.dark : scroll.light }
        Rectangle { visible: bv.bevelled; x: 0; y: 0; width: 1; height: bv.height
                    color: bv.sunken ? scroll.dark : scroll.light }
        Rectangle { visible: bv.bevelled; x: 0; y: bv.height - 1; width: bv.width; height: 1
                    color: bv.sunken ? scroll.light : scroll.dark }
        Rectangle { visible: bv.bevelled; x: bv.width - 1; y: 0; width: 1; height: bv.height
                    color: bv.sunken ? scroll.light : scroll.dark }
    }

    // A 9x5 pixel triangle, five 1px rows. Geometry, not a glyph.
    component Arrow: Item {
        id: ar
        property bool down: false
        property color ink: Theme.textDim
        Repeater {
            model: 5
            Rectangle {
                width: 2 * (ar.down ? (4 - index) : index) + 1
                height: 1
                color: ar.ink
                x: Math.floor((ar.width - width) / 2)
                y: Math.floor((ar.height - 5) / 2) + index
            }
        }
    }

    // A stepper button: presses IN and auto-repeats.
    component Stepper: Item {
        id: st
        property bool pointsDown: false
        property bool held: false
        property bool live: true
        signal step()
        Bevel { anchors.fill: parent; sunken: st.held }
        Arrow {
            anchors.fill: parent
            down: st.pointsDown
            ink: !st.live ? Theme.dim
               : (st.held ? Theme.accent : (st.hovered ? Theme.text : Theme.textDim))
            x: st.held ? 1 : 0
            y: st.held ? 1 : 0
        }
        property bool hovered: ma.containsMouse
        MouseArea {
            id: ma
            hoverEnabled: true
            anchors.fill: parent
            enabled: st.live
            cursorShape: st.live ? Qt.PointingHandCursor : Qt.ArrowCursor
            onPressed: { st.held = true; st.step(); repeat.interval = 300; repeat.restart(); }
            onReleased: { st.held = false; repeat.stop(); }
            onCanceled: { st.held = false; repeat.stop(); }
        }
        Timer {
            id: repeat
            repeat: true
            onTriggered: { interval = 60; if (st.live) st.step(); else stop(); }
        }
    }

    // ---- the track --------------------------------------------------------
    Bevel {
        anchors.fill: parent
        faceColor: scroll.trackC
        sunken: !scroll.isFlat
        bevelled: !scroll.isFlat
    }

    // ---- the thumb --------------------------------------------------------
    Bevel {
        id: thumb
        x: scroll.barStyle === "beveled" ? 1 : 0
        width: scroll.barW - 2 * x
        // Snap to the pixel grid: a 1px bevel on a half pixel shimmers.
        y: Math.round(scroll._thumbY)
        height: Math.round(scroll._thumbH)
        faceColor: drag.pressed ? Theme.accent
                 : (scroll.isFlat ? (drag.containsMouse ? Theme.text : Theme.textDim) : scroll.face)
        sunken: false

        MouseArea {
            id: drag
            anchors.fill: parent
            hoverEnabled: scroll.isFlat
            enabled: scroll._scrollable
            cursorShape: Qt.ArrowCursor
            property real grabOffset: 0
            onPressed: (m) => {
                const p = mapToItem(scroll, m.x, m.y);
                grabOffset = p.y - thumb.y;
            }
            onPositionChanged: (m) => {
                const denom = scroll._avail - scroll._thumbH;
                if (denom <= 0) return;
                const p = mapToItem(scroll, m.x, m.y);
                const frac = Math.max(0, Math.min(1, (p.y - grabOffset - scroll._pad) / denom));
                scroll._clampTo(frac * scroll._max);
            }
        }
    }

    // ---- the steppers (win31 only) ---------------------------------------
    Stepper {
        visible: scroll.isWin31
        width: scroll.btn; height: scroll.btn
        anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter
        live: scroll.canUp
        pointsDown: false
        onStep: scroll._clampTo(scroll.flick.contentY - scroll.stepPx)
    }
    Stepper {
        visible: scroll.isWin31
        width: scroll.btn; height: scroll.btn
        anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter
        live: scroll.canDown
        pointsDown: true
        onStep: scroll._clampTo(scroll.flick.contentY + scroll.stepPx)
    }
}
