import QtQuick

// USE THIS, NOT A BARE `ListView`, for every scrollable list in the panel.
// It is a plain ListView with the panel's scroll physics bound to the Kinetic
// singleton, so a change to `kinetic_friction` propagates here instead of
// having to be chased through six files. Everything else — model, delegate,
// section, header, attached `ListView.*` properties in delegates — behaves
// exactly as it does on the base type, because that is all this is.
ListView {
    flickDeceleration: Kinetic.flickDeceleration
    maximumFlickVelocity: Kinetic.maximumFlickVelocity
    // The panel is pointer-driven and every list here is finite: overshooting
    // past the ends reads as a glitch rather than as elasticity, and a list
    // whose model is replaced under the pointer (Procs re-sorts every 2 s)
    // would be fighting the refresh. Override per instance if you really need
    // DragOverBounds.
    boundsBehavior: Flickable.StopAtBounds
}
