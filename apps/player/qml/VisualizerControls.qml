import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC
import "../../qmlcommon"

Item {
    id: root
    readonly property var settingsState: Visualizer.stateInfo
    property bool advanced: false
    property int presetIndex: -1
    function send(op) { Visualizer.command(op); }
    function showMenu(x,y,items) {
        var p=menu.parent.mapFromItem(null,x,y);
        menu.show(p.x,p.y,items);
    }
    CtxMenu { id: menu; parent: root.Window.window ? root.Window.window.contentItem : root }
    KineticFlickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.height+16
        clip: true
        QQC.ScrollBar.vertical: VScroll { id: controlScroll }
        Column {
            id: column
            x: 8; y: 8; width: parent.width-16-controlScroll.barW
            spacing: 6
            enabled: root.settingsState.ready === true
            PixelText {
                width: parent.width
                color: Theme.textDim
                text: Number(Visualizer.statistics.actualFps || 0).toFixed(1)+" fps · "
                      +(Visualizer.statistics.renderWidth || 0)+" × "+(Visualizer.statistics.renderHeight || 0)
            }
            Flow {
                width: parent.width; spacing: 4
                HeaderButton { label: "randomise (R)"; onClicked: Visualizer.key("r") }
                HeaderButton { label: root.settingsState.paused ? "resume changes" : "pause changes"
                    lit: root.settingsState.paused; onClicked: Visualizer.key(" ") }
                HeaderButton { label: "save look (S)"; onClicked: Visualizer.key("s") }
            }
            SelectButton {
                width: parent.width
                label: root.presetIndex>=0 && root.presetIndex<Visualizer.presetNames.length
                       ? Visualizer.presetNames[root.presetIndex] : "saved looks"
                options: Visualizer.presetNames.map((name,i)=>({label:name,value:i}))
                onPicked: (x,y,items)=>root.showMenu(x,y,items)
                onChose: value => { root.presetIndex=Number(value); root.send({op:"preset",index:Number(value)}); }
            }
            HeaderButton {
                visible: root.presetIndex>=0 && root.presetIndex<Visualizer.presetNames.length
                label: "delete selected look"
                onClicked: { root.send({op:"deletePreset",index:root.presetIndex}); root.presetIndex=-1; }
            }
            Repeater {
                model: [{kind:"W",label:"wave shape (W)"},{kind:"D",label:"distortion (C)"},
                        {kind:"C",label:"colours (X)"},{kind:"P",label:"particles (N)"}]
                Column {
                    required property var modelData
                    width: column.width; spacing: 2
                    PixelText { text: modelData.label; color: Theme.textDim }
                    SelectButton {
                        width: parent.width
                        label: ((root.settingsState.selections || {})[modelData.kind] || "").replace(/_/g," ")
                        options: ((Visualizer.choices[modelData.kind]) || []).map(n=>({label:n.replace(/_/g," "),value:n}))
                        onPicked: (x,y,items)=>root.showMenu(x,y,items)
                        onChose: value=>root.send({op:"select",kind:modelData.kind,name:value})
                    }
                }
            }
            Repeater {
                model: Visualizer.dials
                Column {
                    required property var modelData
                    required property int index
                    width: column.width; spacing: 2
                    visible: index<8 || root.advanced
                    readonly property real current: Number((root.settingsState.values || {})[modelData.name] || 0)
                    enabled: modelData.name!=="rate" || !root.settingsState.paused
                    PixelText {
                        width: parent.width
                        text: modelData.label+"  "+Number(parent.current.toFixed(2))
                        color: Theme.textDim
                    }
                    Slider {
                        width: parent.width
                        from: modelData.logarithmic ? 0 : modelData.minimum
                        to: modelData.logarithmic ? 1 : modelData.maximum
                        step: modelData.logarithmic ? .005 : modelData.step
                        value: modelData.logarithmic ? Math.log(Math.max(modelData.minimum,parent.current)/modelData.minimum)/Math.log(modelData.maximum/modelData.minimum) : parent.current
                        onMoved: v=>root.send({op:"dial",name:modelData.name,
                            value:modelData.logarithmic ? modelData.minimum*Math.pow(modelData.maximum/modelData.minimum,v) : v})
                    }
                }
            }
            HeaderButton { label: root.advanced ? "hide advanced controls" : "advanced controls"
                onClicked: root.advanced=!root.advanced }
            Repeater {
                model: Visualizer.toggles
                HeaderButton {
                    required property var modelData
                    label: modelData.label
                    lit: Boolean((root.settingsState.values || {})[modelData.name])
                    onClicked: root.send({op:"dial",name:modelData.name,value:!lit})
                }
            }
            Column {
                width: parent.width; spacing: 6; visible: root.advanced
                enabled: !root.settingsState.paused
                PixelText { text: "automatic changes (seconds)"; color: Theme.textDim }
                Repeater {
                    model: [{kind:"W",label:"wave shape"},{kind:"D",label:"distortion"},
                            {kind:"C",label:"colours"},{kind:"P",label:"particle lifetime"}]
                    Column {
                        required property var modelData
                        width: column.width; spacing: 2
                        readonly property var pair: ((root.settingsState.values || {}).intervals || {})[modelData.kind] || [0,0]
                        PixelText { text: modelData.label+"  "+parent.pair[0]+"–"+(parent.pair[0]+parent.pair[1]); color: Theme.textDim }
                        Slider { width: parent.width; from: 0; to: 300; step: 1; value: parent.pair[0]
                            onMoved: v=>root.send({op:"interval",kind:modelData.kind,value:[v,Math.max(v,parent.pair[0]+parent.pair[1])]}) }
                        Slider { width: parent.width; from: 0; to: 300; step: 1; value: parent.pair[0]+parent.pair[1]
                            onMoved: v=>root.send({op:"interval",kind:modelData.kind,value:[Math.min(v,parent.pair[0]),v]}) }
                    }
                }
            }
            HeaderButton { label: root.settingsState.comparing ? "return to my settings" : "compare defaults"
                onClicked: root.send({op:"compare"}) }
            HeaderButton { label: "reset all"; enabled: !root.settingsState.comparing; onClicked: root.send({op:"reset"}) }
            PixelText { width: parent.width; wrapMode: Text.Wrap
                text: "Space: playback · Shift+Space: changes\nTab: controls · F11: fullscreen · W/C/X/N: next component · P: particles · R: randomise · S: save look"
                color: Theme.textDim }
        }
    }
}
