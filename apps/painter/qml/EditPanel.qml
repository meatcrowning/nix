import QtQuick

// EDIT MODE'S LEFT COLUMN IS A PLACE TO DROP IMAGES AND A PROMPT BOX, and this
// is the first half [his] "the left side of the program when edit is selected
// should really just be a box to drop the image in and a prompt box".
// Everything else is hidden by Main.qml rather than shown doing nothing: the
// edit graph reads the size out of the FIRST dropped image, takes no negative
// prompt (its negative conditioning is the positive one zeroed out) and carries
// the family's own steps/cfg/shift.
//
// Flux 2 Klein takes MULTIPLE reference images (comfy attaches each as a
// reference latent, chained), so the primary well is joined by a stack of
// extra wells and a compact add target. The primary is the SAME slot as
// the video first frame (App.inputImage) on purpose: painter holds one dropped
// picture, so a frame dropped for a clip is still there if you switch to edit,
// and it is remembered across launches by the prefs key that already existed.
// The extras are their own list (App.editExtraImages).
Panel {
    id: panel
    title: App.referenceImages ? "Reference images" : App.optionalEditImage ? "Source image" : "Images"
    badge: App.referenceImages ? "encoder guidance" : App.optionalEditImage ? (App.inputImage === "" ? "optional · text to image" : "editing") : (App.inputImage === "" ? "drop one" : "")

    ImageInputs { }
}
