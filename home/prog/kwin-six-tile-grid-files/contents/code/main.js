// KWin starts every new output with a 25% / 50% / 25% horizontal layout.
// Convert precisely that default, and nothing else: a layout changed in the
// Tiling Editor is the user's layout and must survive the next KWin start.
const HORIZONTAL = 1;
const VERTICAL = 2;
const THIRD = 1 / 3;
const EPSILON = 0.0001;

function closeTo(a, b) {
    return Math.abs(a - b) < EPSILON;
}

function isDefaultThreeColumns(root) {
    const tiles = root.tiles;
    return root.layoutDirection === HORIZONTAL
        && tiles.length === 3
        && tiles[0].tiles.length === 0
        && tiles[1].tiles.length === 0
        && tiles[2].tiles.length === 0
        && closeTo(tiles[0].relativeGeometry.width, 0.25)
        && closeTo(tiles[1].relativeGeometry.width, 0.5)
        && closeTo(tiles[2].relativeGeometry.width, 0.25);
}

function makeGrid(root) {
    // Removing each stock leaf makes the root empty without disturbing any
    // user-made nested layout (which is filtered out by isDefaultThreeColumns).
    while (root.tiles.length > 0) {
        root.tiles[0].remove();
    }

    // root -> two vertical rows; each row -> three horizontal cells.
    root.split(VERTICAL);
    for (let row = 0; row < 2; ++row) {
        const rowTile = root.tiles[row];
        rowTile.split(HORIZONTAL);
        rowTile.tiles[0].split(HORIZONTAL);

        // The third split initially divides the first half again. Setting the
        // middle cell's left/right edges moves its neighbours with it, leaving
        // exactly one third for every cell in that row.
        const middle = rowTile.tiles[1];
        middle.relativeGeometry = {
            x: THIRD,
            y: row * 0.5,
            width: THIRD,
            height: 0.5,
        };
    }
}

for (const screen of workspace.screens) {
    for (const desktop of workspace.desktops) {
        const root = workspace.rootTile(screen, desktop);
        if (root && isDefaultThreeColumns(root)) {
            makeGrid(root);
        }
    }
}
