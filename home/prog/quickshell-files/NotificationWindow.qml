import QtQuick
import Quickshell
import Quickshell.Wayland

// The toast stack. On the bar's side of the screen it is ATTACHED to the panel
// the way the shortcut notch is (DesktopNotch.qml): each card sits flush
// against the panel's face, reaches NotchModel.overlap under the bar body so
// its mouth opens INTO the panel — its own fill hides the stretch of the bar's
// accent strip crossing it, so the strip reads as detouring around the card —
// and a new card enters by sliding OUT of the panel, clipped at the mouth, so
// it emerges rather than appears. [his] "toasts should appear as if sliding
// out from the panel while still being 'attached' like how the program icon
// bar is."
//
// That needs the panel's FACE, which the layer-shell reserve cannot give us:
// the reserve includes the notch's protrusion and is frozen mid-drag. So on
// the bar's side the surface ignores exclusive zones and spans from the true
// screen edge at a FIXED width — a surface that resizes with the drag lags it
// (the EdgeAccent lesson) — and the stack inside follows ViewMode.liveWidth,
// which lands exactly. Input is masked to the cards' desktop-side part only:
// the mouth region is visually the bar's, and the EdgeGrip drag zone at the
// face must keep working under it.
//
// A corner on the OPPOSITE side from the bar has no panel to attach to and
// keeps the floating look: a Theme.gap margin off the reserved area and the
// short slide-in with the card's own fade.
// Overlay layer, no keyboard focus (never steals focus, like the OSD/launcher).
PanelWindow {
    id: win

    // Which corner the toast stack lives in, decoded from notifCorner
    // ("bottom-right" | "bottom-left" | "top-right" | "top-left").
    readonly property bool _top: SettingsStore.d.notifCorner.indexOf("top") === 0
    readonly property bool _left: SettingsStore.d.notifCorner.indexOf("left") >= 0
    readonly property bool barLeft: SettingsStore.d.barEdge === "left"
    readonly property bool attached: _left === barLeft

    // How far a card reaches under the bar body: the notch's own mouth depth,
    // so the two attachments read as one construction.
    readonly property int mouth: attached ? NotchModel.overlap : 0
    // A card's full width, mouth included; the desktop sees notifWidth of it.
    readonly property int cardW: SettingsStore.d.notifWidth + mouth

    anchors { top: win._top; bottom: !win._top; left: win._left; right: !win._left }
    margins {
        top: Theme.gap; bottom: Theme.gap
        left: win.attached ? 0 : Theme.gap
        right: win.attached ? 0 : Theme.gap
    }

    // Attached: from the screen edge past the widest the panel can be, so the
    // stack can sit at the face at every panel width without the surface ever
    // resizing. Floating: exactly the stack, placed clear of the reserve.
    exclusionMode: win.attached ? ExclusionMode.Ignore : ExclusionMode.Normal
    implicitWidth: win.attached ? ViewMode.maxPx + SettingsStore.d.notifWidth
                                : SettingsStore.d.notifWidth
    implicitHeight: Math.max(1, col.implicitHeight)
    color: "transparent"
    exclusiveZone: 0

    // Stay unmapped while empty so the transparent surface can't eat stray
    // clicks in the corner.
    visible: Notifications.count > 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-notifications"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    // Clicks land only on the cards' desktop-side part. The mouth (and the
    // rest of the bar the attached surface spans) stays the bar's: the grip's
    // drag zone and the panel's own widgets sit under this surface, and an
    // Overlay surface with no mask would swallow every event over them.
    // Floating, the rect is the whole (card-sized) window — no change.
    mask: Region {
        x: win.attached
           ? (win.barLeft ? ViewMode.liveWidth
                          : win.width - ViewMode.liveWidth - SettingsStore.d.notifWidth)
           : 0
        y: 0
        width: win.attached ? SettingsStore.d.notifWidth : win.width
        height: win.height
    }

    // The stack, clipped at the mouth's edge so an entering card emerges from
    // the panel instead of materialising on top of it.
    Item {
        id: holder
        clip: win.attached
        width: win.cardW
        height: parent.height
        x: win.attached
           ? (win.barLeft ? ViewMode.liveWidth - win.mouth
                          : win.width - ViewMode.liveWidth - SettingsStore.d.notifWidth)
           : 0

        Column {
            id: col
            // stack from the anchored corner's vertical edge (top corners grow
            // down, bottom corners grow up)
            anchors {
                left: parent.left; right: parent.right
                top: win._top ? parent.top : undefined
                bottom: win._top ? undefined : parent.bottom
            }
            spacing: Theme.gap

            // Attached: slide out of the panel — from a card-width inside the
            // clip, i.e. fully behind the bar. Floating: the short ±48 nudge
            // (the card's own fade carries the entry there). Ease the stack
            // when one leaves.
            add: Transition {
                NumberAnimation {
                    properties: "x"
                    from: win.attached ? (win.barLeft ? -win.cardW : win.cardW)
                                       : (win._left ? -48 : 48)
                    duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing
                }
            }
            move: Transition {
                NumberAnimation { properties: "y"
                                  duration: ViewMode.ms(ViewMode.slideMs); easing.type: ViewMode.slideEasing }
            }

            Repeater {
                model: Notifications.model
                delegate: NotificationCard {
                    required property var modelData
                    width: col.width
                    notif: modelData
                    attached: win.attached
                    mouthOnLeft: win.barLeft
                }
            }
        }
    }
}
