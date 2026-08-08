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
// bar is." A leaving card plays the same slide in reverse — back INTO the
// panel behind the clip — on the same clock ([his] "toasts should roll up
// like how they roll out ... animation timing is the same as the window
// rolls", docs/DESIGN.md §6.2).
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
    // The stack's shared width: the widest visible card's content-fitted
    // width (NotificationCard.fitW, capped there at notifWidth), so a short
    // toast carries no blank right side. ONE width for the whole stack, not
    // per-card ragged edges — the input mask below is a single rectangle, and
    // a rect over a ragged stack would swallow desktop clicks beside the
    // narrower cards.
    readonly property int stackW: {
        let w = 1;
        for (let i = 0; i < col.children.length; i++) {
            const c = col.children[i];
            if (c && c.fitW !== undefined)
                w = Math.max(w, c.fitW);
        }
        return w;
    }
    // A card's full width, mouth included; the desktop sees stackW of it.
    readonly property int cardW: stackW + mouth

    // What the cards render: the tracked list, plus any card still playing its
    // exit. Quickshell drops a closed notification from trackedNotifications
    // the same frame, and a Repeater bound to that model destroys the card
    // with it — an exit animation needs the card to LINGER. So the window
    // mirrors the tracked list here, each card holds a RetainableLock on its
    // notification (NotificationCard.qml) so the object stays readable, and a
    // removal only STARTS the card's roll back into the panel; the card falls
    // out of this array when its slide lands.
    property var stack: []

    function retire(n) {
        win.stack = win.stack.filter(x => x !== n);
    }

    Component.onCompleted: {
        // Anything already tracked when the window comes up (a toast arriving
        // in the same frame the panel builds).
        const vals = Notifications.model.values;
        for (let i = 0; i < vals.length; i++)
            win.stack = win.stack.concat([vals[i]]);
    }

    Connections {
        target: Notifications.model
        function onObjectInsertedPost(object, index) {
            win.stack = win.stack.concat([object]);
        }
        function onObjectRemovedPost(object, index) {
            for (let i = 0; i < col.children.length; i++) {
                const c = col.children[i];
                if (c && c.notif === object) {
                    c.leave();
                    return;
                }
            }
            win.retire(object);   // no card built for it: nothing to animate
        }
    }

    anchors { top: win._top; bottom: !win._top; left: win._left; right: !win._left }
    margins {
        top: Theme.gap; bottom: Theme.gap
        left: win.attached ? 0 : Theme.gap
        right: win.attached ? 0 : Theme.gap
    }

    // Attached: from the screen edge past the widest the panel can be, so the
    // stack can sit at the face at every panel width without the surface ever
    // resizing. Floating: the widest a card can be, placed clear of the
    // reserve — also fixed, the content-fitted stack sits at its outer edge.
    exclusionMode: win.attached ? ExclusionMode.Ignore : ExclusionMode.Normal
    implicitWidth: win.attached ? ViewMode.maxPx + SettingsStore.d.notifWidth
                                : SettingsStore.d.notifWidth
    implicitHeight: Math.max(1, col.implicitHeight)
    color: "transparent"
    exclusiveZone: 0

    // Stay unmapped while empty so the transparent surface can't eat stray
    // clicks in the corner. Follows the lingering stack, not the tracked
    // count: unmapping on dismissal would cut the exit slide off mid-frame.
    visible: win.stack.length > 0

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "qs-notifications"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    // Clicks land only on the cards' desktop-side part. The mouth (and the
    // rest of the bar the attached surface spans) stays the bar's: the grip's
    // drag zone and the panel's own widgets sit under this surface, and an
    // Overlay surface with no mask would swallow every event over them.
    // Floating, the rect is the stack, at the window's outer edge — the slack
    // the content-fitted cards leave against the cap must not eat clicks.
    mask: Region {
        x: win.attached
           ? (win.barLeft ? ViewMode.liveWidth
                          : win.width - ViewMode.liveWidth - win.stackW)
           : (win._left ? 0 : win.width - win.stackW)
        y: 0
        width: win.stackW
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
                          : win.width - ViewMode.liveWidth - win.stackW)
           : (win._left ? 0 : win.width - win.stackW)

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
                // ScriptModel diffs against the previous array: an arrival
                // builds one new delegate, a retirement destroys one — a plain
                // JS array as the model would rebuild every card on each
                // change, restarting their expiry timers and animations.
                model: ScriptModel { values: win.stack }
                delegate: NotificationCard {
                    required property var modelData
                    width: col.width
                    notif: modelData
                    attached: win.attached
                    mouthOnLeft: win.barLeft
                    floatLeft: win._left
                    onDeparted: win.retire(modelData)
                }
            }
        }
    }
}
