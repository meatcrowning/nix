import QtQuick

// The videos a reply carries, stacked in the order the model showed them.
//
// Same API as `../VideoDeck.qml` — `entries`, `stage`, `host`,
// `contextRequested` — and the same shape: deliberately NOT a grid, because a
// video is watched one at a time and four muted tiles playing at once is
// exactly what the image gallery's grid exists to avoid for stills.
//
// It has an Oxygen twin only so the cards it builds are the Oxygen ones: a
// `VideoCard` named from inside `+oxygen/` resolves to the sibling here. Every
// pixel it puts on screen is drawn by that card.
Column {
    id: deck

    property string face: "oxygen"

    property var entries: []
    property Item stage: null
    property var host: null
    signal contextRequested(string path, real x, real y)

    spacing: 6

    Repeater {
        model: deck.entries ? deck.entries.length : 0
        delegate: VideoCard {
            required property int index
            width: deck.width
            entry: deck.entries[index]
            stage: deck.stage
            host: deck.host
            onContextRequested: (p, x, y) => deck.contextRequested(p, x, y)
        }
    }
}
