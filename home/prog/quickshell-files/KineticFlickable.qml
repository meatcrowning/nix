import QtQuick

// USE THIS, NOT A BARE `Flickable`, for every scrollable pane in the panel.
// See KineticListView.qml — same contract, same single source of truth
// (Kinetic.qml).
Flickable {
    flickDeceleration: Kinetic.flickDeceleration
    maximumFlickVelocity: Kinetic.maximumFlickVelocity
    boundsBehavior: Flickable.StopAtBounds
}
