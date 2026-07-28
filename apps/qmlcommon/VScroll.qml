import QtQuick
import QtQuick.Controls.Basic

// THE scrollbar. `docs/DESIGN.md` §9.2 states it as one idiom for the whole desktop —
// *"there should be a scrollbar wherever appropriate! please"* — visible only on
// overflow, brighter on hover, accent while pressed, a 120ms opacity fade:
//
//     KineticListView { ScrollBar.vertical: VScroll {} }
//
// It lived as four separate copies (player's, painter's, and an inline
// `component VScroll` in each of filer's and reader's panes) before this file;
// §19.1 lists that duplication as a real divergence, and `apps/AGENTS.md` says a
// component that exists in more than one app belongs in `qmlcommon/`. This is
// that home. The three existing copies are byte-identical to it and should come
// here as each of those files is next touched — a mechanical change, but one
// that belongs to whoever is already editing them.
//
// The 120ms is deliberately NOT the desktop's 260ms slide: it is an opacity
// fade with no travel to read (§6.2.1's non-participants table).
ScrollBar {
    id: vb

    policy: ScrollBar.AsNeeded
    width: 9

    contentItem: Rectangle {
        implicitWidth: 9
        color: vb.pressed ? Theme.accent : Theme.textDim
        opacity: vb.size < 1 ? (vb.active ? 0.9 : 0.5) : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }
    background: Rectangle {
        color: Theme.bgAlt
        opacity: vb.size < 1 && vb.active ? 0.4 : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
    }
}
