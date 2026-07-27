import QtQuick

// The shared body of the three history widgets (cpu, gpu, eth): a title, a
// ChartCanvas of one or more ring buffers, and a legend under it. CpuContent /
// GpuContent / EthContent are each about ten lines on top of this.
//
// It is a CONTENT component, i.e. it draws a widget and owns no data and no
// window. That is what lets the same widget appear as a hover popup on the
// wallpaper (classic mode) and as a tile in the dock's grid, from one source —
// see DockGrid.qml. Two rules follow from being used in both places:
//
//   * It must STRETCH. In a popup it is given its implicit size; in a grid cell
//     it is given the cell. So the title sits at the top, the legend at the
//     bottom, and the chart takes whatever is left — never a fixed 196x96.
//   * It must be able to go DORMANT. Both copies exist in the QML tree at once,
//     but only one is on screen, so `active` gates the repaints. Anything that
//     costs something when nobody is looking hangs off that flag.
Item {
    id: root

    property string title: ""
    property alias series: chart.series
    property alias scaleMax: chart.scaleMax
    property alias autoFloor: chart.autoFloor
    property alias midline: chart.midline
    property alias pointCount: chart.pointCount
    // The y-axis top actually used — the eth widget prints it as its peak.
    readonly property real axisMax: chart.axisMax

    // Defaults to FALSE, and every host sets it: the popup passes its `open`,
    // DockTile binds it to the dock's visibility. A `true` default would mean a
    // grid tile polls once at construction, before that Binding has applied —
    // measured as a full /proc scan and a drive scan on every reload, for a
    // widget nobody was looking at.
    property bool active: false
    property int pad: 10
    property int spacing: 6
    property int chartMinHeight: 96

    // Legend contents (a Row of readouts, usually). Declared as the default
    // property so a consumer just writes its readouts inside MetricChart {}.
    default property alias legend: legendCol.data

    implicitWidth: 220
    implicitHeight: pad * 2 + titleText.height + spacing
                    + chartMinHeight + spacing + legendCol.implicitHeight

    function repaint() { chart.repaint(); }

    PixelText {
        id: titleText
        anchors { top: parent.top; topMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        text: root.title
        color: Theme.accent
    }

    Column {
        id: legendCol
        anchors { bottom: parent.bottom; bottomMargin: root.pad; horizontalCenter: parent.horizontalCenter }
        spacing: 2
    }

    ChartCanvas {
        id: chart
        active: root.active
        anchors {
            top: titleText.bottom; topMargin: root.spacing
            bottom: legendCol.top; bottomMargin: root.spacing
            left: parent.left; leftMargin: root.pad
            right: parent.right; rightMargin: root.pad
        }
    }
}
