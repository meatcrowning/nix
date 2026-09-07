// Kickoff itself has no popup-position setting. On this desktop its panel
// anchor is (0, 22), which is inside the left 42px panel. Plasma exposes this
// as its only PopupMenu surface at that exact top-left anchor. Keep the popup
// at its client-selected size and move only its frame into the usable area.

const TOP_PANEL_HEIGHT = 22;
const LEFT_PANEL_WIDTH = 42;
const POPUP_MENU = 18;

function moveKickoffPopup(window) {
    const frame = window.frameGeometry;
    if (window.resourceClass !== "org.kde.plasmashell"
        || window.windowType !== POPUP_MENU
        || frame.x !== 0
        || frame.y !== TOP_PANEL_HEIGHT) {
        return;
    }

    window.frameGeometry = {
        x: LEFT_PANEL_WIDTH,
        y: TOP_PANEL_HEIGHT,
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
