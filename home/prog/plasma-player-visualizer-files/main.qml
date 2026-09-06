import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support

// Compact fallback for the Plasma media controller.  Its producer is shared
// with the Oxygen decoration, so this applet never starts a second Cava.
PlasmoidItem {
    id: root
    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    preferredRepresentation: compactRepresentation
    property var levels: []

    P5Support.DataSource {
        id: state
        engine: "executable"
        onNewData: (source, data) => {
            try {
                const parsed = JSON.parse(data.stdout || "{}");
                root.levels = parsed.levels || [];
            } catch (_) {
                root.levels = [];
            }
        }
    }

    // Plasma does not expose a portable file watcher to applets. Polling this
    // tmpfs snapshot at the producer's 60 Hz cadence is cheap and coalesces
    // naturally if the panel is busy.
    Timer {
        interval: 34; repeat: true; running: true
        onTriggered: state.connectSource("sh -c 'cat \"$XDG_RUNTIME_DIR/player-visualizer.json\" 2>/dev/null || true'")
    }

    compactRepresentation: Item {
        implicitWidth: 72
        implicitHeight: Math.max(22, Plasmoid.configuration.panelHeight || 22)
        Repeater {
            model: root.levels.length
            Rectangle {
                required property int index
                x: Math.round(parent.width * index / root.levels.length)
                width: Math.max(1, Math.round(parent.width * (index + 1) / root.levels.length) - x)
                anchors.bottom: parent.bottom
                height: Math.max(1, parent.height * Math.pow((root.levels[index] || 0) / 100, 0.55))
                color: PlasmaCore.Theme.textColor
            }
        }
    }
}
