import QtQuick

Item {
    id: probe
    property string text: ""
    property bool active: false
    property var service: typeof App.inspection !== "undefined" ? App.inspection : null
    property bool ready: typeof App.ready !== "undefined" && App.ready
    onReadyChanged: refresh()
    property string identity: "tokens-" + Date.now() + "-" + Math.random()
    property string request: ""
    property int revision: 0
    property var result: ({})
    readonly property int count: result.count === undefined ? -1 : Math.max(0, result.count - (result.template_tokens || 0))
    readonly property var boundaries: result.utf16_boundaries || []
    readonly property string tip: result.error || "Prompt tokens only; excludes the MOSS chat wrapper. Before weighting, wildcard expansion or layout compilation."
    function refresh() {
        revision++
        result = ({})
        delay.stop()
        if (active && service) delay.restart()
    }
    onTextChanged: refresh()
    onActiveChanged: refresh()
    Component.onCompleted: refresh()
    Timer {
        id: delay
        interval: 350
        onTriggered: {
            probe.request = probe.identity + ":" + probe.revision
            probe.service.tokenize(probe.request, probe.text)
        }
    }
    Connections {
        target: probe.service
        function onTokenized(identity, text, result) {
            if (probe.active && identity === probe.request && text === probe.text
                    && identity === probe.identity + ":" + probe.revision)
                probe.result = result
        }
    }
}
