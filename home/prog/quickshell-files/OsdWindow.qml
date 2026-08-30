import QtQuick
import Quickshell
import Quickshell.Wayland

// A transient OSD for volume / brightness. A short VERTICAL bar that is
// ATTACHED to the panel the way the shortcut notch (DesktopNotch.qml) and the
// notification stack (NotificationWindow.qml) are: it sits flush against the
// panel's face near the bar's bottom, its mouth reaching NotchModel.overlap
// under the bar body in the bar's own background — so the inner-edge accent
// strip reads as detouring around it — and it enters by sliding OUT of the
// panel, clipped at the mouth, so it emerges from the sidebar rather than
// materialising beside it. It slides back INTO the panel behind the clip when
// it auto-hides. [his] the OSD should read as part of the panel, like the
// toasts do. A vertical fill bar inside shows the current level.
// One per screen; all observe the shared Osd singleton. Instantiated via
// Variants in shell.qml.
PanelWindow {
    id: w
    required property var modelData
    screen: modelData

    // Which side the bar hugs — the card attaches to it, its mouth on that side.
    // On a top/bottom bar there is no vertical face to emerge from, so the card
    // docks to the right screen edge with a plain gap instead of a mouth. That
    // is what `effBar` is: the inset the card sits at, the panel's live width
    // on a vertical bar and one gap on a horizontal one.
    readonly property bool barLeft: !ViewMode.barHorizontal
                                    && SettingsStore.d.barEdge === "left"
    readonly property int effBar: ViewMode.barHorizontal ? Theme.gap : ViewMode.liveWidth
    // How far the card reaches under the bar body: the notch's own mouth depth,
    // so the OSD, the notch and the toasts read as one construction.
    readonly property int mouth: ViewMode.barHorizontal ? 0 : NotchModel.overlap
    // The card's DESKTOP-visible width; the mouth is added on top of it.
    readonly property int cardBodyW: 40
    readonly property int cardW: cardBodyW + mouth

    // Stay mapped through the slide-out, then hide once the card has travelled
    // back into the panel behind the clip.
    visible: Osd.active || Math.abs(card.x - card.hidden) > 1

    // Span from the true screen edge on the bar's side past the widest the panel
    // can be, ignoring exclusive zones, so the card can sit at the panel's face
    // at every panel width without the surface ever resizing (the EdgeAccent /
    // notification lesson). Docked near the bottom, a gap off the screen edge.
    anchors { bottom: true; left: w.barLeft; right: !w.barLeft }
    // ...and clear of a bottom bar, which the ignored exclusive zone would
    // otherwise let it sit under.
    margins.bottom: Theme.gap
        + ((ViewMode.barHorizontal && !ViewMode.barAtStart) ? Theme.barWidth : 0)

    exclusionMode: ExclusionMode.Ignore
    implicitWidth: ViewMode.maxPx + cardW
    implicitHeight: 184
    color: "transparent"
    exclusiveZone: 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-osd"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    // The surface spans across the bar now, so an Overlay with no mask would
    // swallow every click on the panel's widgets and the EdgeGrip beneath it.
    // The OSD is non-interactive, so mask to nothing: every event passes through.
    mask: Region {}

    // The card, clipped at the mouth's edge so it emerges from the panel instead
    // of appearing on top of it. Held a card-width inside the clip (fully behind
    // the bar) when hidden.
    Item {
        id: holder
        clip: true
        anchors { top: parent.top; bottom: parent.bottom }
        width: w.cardW
        x: w.barLeft ? (w.effBar - w.mouth)
                     : (parent.width - w.effBar - w.cardBodyW)

        Rectangle {
            id: card
            anchors { top: parent.top; bottom: parent.bottom }
            width: parent.width

            // Slide out of the panel from behind the clip. Open: flush at the
            // panel's face (x 0). Hidden: a full card-width behind the bar.
            readonly property real shown: 0
            readonly property real hidden: w.barLeft ? -w.cardW : w.cardW
            x: Osd.active ? shown : hidden
            Behavior on x { NumberAnimation { duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing } }

            // Pure black card, like the runner / power menu / cheatsheet and the
            // bar itself — so the mouth's fill covers the accent strip crossing
            // it invisibly, the strip reading as interrupted. Square corners: the
            // outline below is the notch's three-sided construction, which only
            // meets the panel seam square.
            radius: 0
            color: Theme.bg

            readonly property int lineW: Math.max(2, Theme.windowBorderWidth)
            // The arms run to the panel's face plus one line width: the corner is
            // painted over the strip rather than shared between two shapes.
            readonly property int armW: width - w.mouth + lineW

            readonly property color tint: Osd.kind === "brightness"
                                        ? (Osd.negative ? Theme.crit : Theme.warn)
                                        : Osd.muted ? Theme.crit : Theme.info
            // 0..1 fill fraction; a muted sink reads as empty.
            readonly property real level: (Osd.kind === "volume" && Osd.muted)
                                        ? 0 : Math.max(0, Math.min(100, Osd.value)) / 100

            // ---- the attached outline: three sides, in the bar's accent -------
            // (DesktopNotch.qml's outline, so the OSD and the notch read as one
            // construction — the mouth side is left open so it opens INTO the
            // panel.)
            Rectangle {   // the desktop-facing side
                x: w.barLeft ? card.width - card.lineW : 0
                width: card.lineW
                height: parent.height
                color: Theme.accent
            }
            Rectangle {   // top arm
                x: w.barLeft ? w.mouth - card.lineW : 0
                y: 0
                width: card.armW
                height: card.lineW
                color: Theme.accent
            }
            Rectangle {   // bottom arm
                x: w.barLeft ? w.mouth - card.lineW : 0
                y: parent.height - card.lineW
                width: card.armW
                height: card.lineW
                color: Theme.accent
            }

            // The content sits in the DESKTOP-visible face only; the mouth is
            // bare fill under the bar.
            Item {
                id: face
                anchors { top: parent.top; bottom: parent.bottom }
                width: w.cardBodyW
                x: w.barLeft ? w.mouth : 0

                // kind label at the top
                PixelText {
                    id: kindLabel
                    anchors.top: parent.top
                    anchors.topMargin: 6
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Osd.kind === "brightness" ? (Osd.negative ? "gma" : "bri") : "vol"
                    color: card.tint
                }

                // value at the bottom ("x" when muted)
                PixelText {
                    id: valLabel
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: (Osd.kind === "volume" && Osd.muted) ? "x" : Osd.shown
                    color: Theme.text
                }

                // vertical level bar between the two labels — fills from the
                // bottom up
                Rectangle {
                    id: track
                    anchors.top: kindLabel.bottom
                    anchors.bottom: valLabel.top
                    anchors.topMargin: 6
                    anchors.bottomMargin: 6
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 12
                    radius: 0
                    color: Theme.highlight
                    border.color: Theme.border
                    border.width: 1

                    // Normally stands up from the bottom. In negative brightness
                    // it HANGS DOWN FROM THE TOP instead, so the range below
                    // hardware zero reads as depth rather than as a level.
                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: Osd.negative ? parent.top : undefined
                        anchors.bottom: Osd.negative ? undefined : parent.bottom
                        anchors.margins: 2
                        height: Math.max(0, (track.height - 4) * card.level)
                        radius: 0
                        color: card.tint
                        Behavior on height { NumberAnimation { duration: ViewMode.ms(140); easing.type: ViewMode.slideEasing } }
                    }
                }
            }
        }
    }
}
