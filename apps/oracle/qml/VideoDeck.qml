import QtQuick

// The videos a reply carries, stacked in the order the model showed them.
//
// The gallery's counterpart for moving pictures, and deliberately NOT a grid:
// a video is watched one at a time, and four muted tiles playing at once is
// exactly what ImageGallery's grid exists to avoid for stills. One card per
// video, full width; failures keep their crit line among them, in place, so
// the third video failing does not look like the second one being shown twice
// (docs/DESIGN.md §10).
Column {
    id: deck

    // The turn's `videos` array, already parsed.
    property var entries: []

    spacing: 6

    Repeater {
        model: deck.entries ? deck.entries.length : 0
        delegate: VideoCard {
            required property int index
            width: deck.width
            entry: deck.entries[index]
        }
    }
}
