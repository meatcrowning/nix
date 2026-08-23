import QtQuick
import QtQuick.Controls

// The conversation's frame in a Plasma session: the KStyle's own `Frame`,
// painted by qqc2-desktop-style, so the view and the compose box below it are
// drawn by the same hand. They were not — the view was a 1px rounded Rectangle
// of ours sitting directly under `+plasma/PromptBox.qml`'s real Frame, which is
// the "one odd window" seam a KDE face exists to close: two surrounds, two
// different reliefs, one window.
//
// Same API as ../ViewFrame.qml — put content inside it, read `pad` for the
// inset — so Root.qml is untouched; the file selector picks between the two.
// The inset is the FRAME'S OWN padding here, not our 8: the style decides how
// far its frame stands off what it surrounds.
Frame {
    id: root
    property string face: "plasma"
    readonly property int pad: Math.round(root.leftPadding)
    default property alias content: inner.data

    // Explicitly the contentItem rather than a declared child: `content` above
    // has taken over the default property, and a child declared here would be
    // assigned into itself.
    contentItem: Item { id: inner }
}
