// Kickoff has no popup-position setting. Its top-left panel anchor can be
// above or inside the left panel. Keep its client-selected size and move
// only the frame clear of both panels, including the top-edge shadow.

const TOP_PANEL_HEIGHT = 22;
const LEFT_PANEL_WIDTH = 42;
const TOP_PANEL_GAP = 6;
const POPUP_MENU = 18;

function moveKickoffPopup(window) {
    const frame = window.frameGeometry;
    if (!["plasmashell", "org.kde.plasmashell"].includes(window.resourceClass)
        || window.windowType !== POPUP_MENU
        || (frame.x !== 0 && frame.x !== LEFT_PANEL_WIDTH)
        || frame.y < 0 || frame.y >= TOP_PANEL_HEIGHT + TOP_PANEL_GAP) {
        return;
    }

    window.frameGeometry = {
        x: LEFT_PANEL_WIDTH,
        y: TOP_PANEL_HEIGHT + TOP_PANEL_GAP,
        width: frame.width,
        height: frame.height,
    };
}

function watch(window) {
    moveKickoffPopup(window);
    window.frameGeometryChanged.connect(() => moveKickoffPopup(window));
}

workspace.windowList().forEach(watch);
workspace.windowAdded.connect(watch);
