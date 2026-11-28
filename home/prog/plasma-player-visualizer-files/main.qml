pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

// Output spectrum beside the Plasma media controller. Its producer is shared
// with the Oxygen decoration, so this applet never starts a second Cava.
PlasmoidItem {
    id: root
    Plasmoid.status: hasAudio ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.HiddenStatus
    preferredRepresentation: compactRepresentation
    // Panel sizing may select the full representation even for a tiny applet.
    fullRepresentation: compactRepresentation
    property var levels: []
    property double lastAudio: 0
    property bool hasAudio: false
    Layout.minimumWidth: hasAudio ? 72 : 0
    Layout.preferredWidth: hasAudio ? 72 : 0
    Layout.maximumWidth: hasAudio ? 72 : 0

    P5Support.DataSource {
        id: state
        engine: "executable"
        onNewData: (source, data) => {
            disconnectSource(source);
            try {
                const parsed = JSON.parse(data.stdout || "{}");
                root.levels = Date.now() / 1000 - Number(parsed.updated || 0) < 2
                    ? parsed.levels || [] : [];
                if (root.levels.some(level => level > 0)) root.lastAudio = Date.now();
                root.hasAudio = Date.now() - root.lastAudio < 1200;
            } catch (_) {
                root.levels = [];
                root.hasAudio = false;
            }
        }
    }

    // Plasma does not expose a portable file watcher to applets. Polling this
    // tmpfs snapshot at 30 Hz; disconnect each completed command so the next
    // tick executes it again instead of retaining the first result forever.
    Timer {
        interval: 34; repeat: true; running: true
        onTriggered: state.connectSource("sh -c 'cat \"$XDG_RUNTIME_DIR/player-visualizer-panel.json\" 2>/dev/null || true'")
    }

    compactRepresentation: Item {
        implicitWidth: root.hasAudio ? 72 : 0
        Layout.minimumWidth: implicitWidth
        Layout.preferredWidth: implicitWidth
        Layout.maximumWidth: implicitWidth
        implicitHeight: Math.max(22, Plasmoid.configuration.panelHeight || 22)
        visible: root.hasAudio
        Repeater {
            model: root.levels.length
            Rectangle {
                required property int index
                x: Math.round(parent.width * index / root.levels.length)
                width: Math.max(1, Math.round(parent.width * (index + 1) / root.levels.length) - x)
                anchors.bottom: parent.bottom
                height: Math.max(1, parent.height * Math.pow((root.levels[index] || 0) / 100, 0.55))
                color: Kirigami.Theme.textColor
            }
        }
    }
}
