import QtQuick

// USE THIS, NOT A BARE `GridView`, for every scrollable grid in the panel.
// See KineticListView.qml — same contract, same single source of truth
// (Kinetic.qml), just the grid flavour.
GridView {
    flickDeceleration: Kinetic.flickDeceleration
    maximumFlickVelocity: Kinetic.maximumFlickVelocity
    boundsBehavior: Flickable.StopAtBounds
}
