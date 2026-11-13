import QtQuick
import QtQuick.Controls
import "../../qmlcommon"

// One transcript row. Prose rows show their text; tool, command and file
// rows fold to one line until clicked; approvals carry their own buttons.
// Every string here is untrusted CLI output: plain text, or markdown that
// session.md_safe() has already defused (docs/DESIGN.md 2.6).
Item {
    id: row
    required property int index
    required property string iid
    required property string kind
    required property string text
    required property string title
    required property string detail
    required property string status
    required property var meta
    required property bool open
    required property string md
    property Item host

    readonly property color fg: host ? host.fg : Theme.text
    readonly property color fgDim: host ? host.fgDim : Theme.textDim
    readonly property bool foldable: kind === "tool" || kind === "command"
                                     || kind === "file_change" || kind === "reasoning"
    readonly property string statusWord: ({
        "running": "running", "completed": "done", "failed": "failed",
        "declined": "declined", "denied": "denied", "waiting": "waiting",
        "allowed": "allowed", "interrupted": "interrupted" })[status] || status

    height: body.implicitHeight
    implicitHeight: body.implicitHeight

    Column {
        id: body
        anchors { left: parent.left; right: parent.right; leftMargin: 10; rightMargin: 10 }
        spacing: 3

        // ---- you ------------------------------------------------------------
        Rectangle {
            visible: row.kind === "user"
            width: parent.width
            height: visible ? userCol.implicitHeight + 10 : 0
            color: Qt.rgba(palette.highlight.r, palette.highlight.g, palette.highlight.b, 0.18)
            radius: Theme.rounding
            Column {
                id: userCol
                anchors { left: parent.left; right: parent.right; margins: 6
                          verticalCenter: parent.verticalCenter }
                PixelText { text: "you"; color: row.fgDim }
                TextEdit {
                    width: parent.width
                    text: row.kind === "user" ? row.text : ""
                    textFormat: TextEdit.PlainText
                    readOnly: true
                    selectByMouse: true
                    persistentSelection: true
                    wrapMode: TextEdit.Wrap
                    font: row.host ? row.host.monoFont : Qt.application.font
                    color: row.fg
                    selectionColor: palette.highlight
                    selectedTextColor: palette.highlightedText
                }
                PixelText {
                    visible: row.kind === "user" && row.meta && row.meta.images
                             && row.meta.images.length > 0
                    text: visible ? row.meta.images.length + " image(s)" : ""
                    color: row.fgDim
                }
            }
        }

        // ---- assistant / plan ------------------------------------------------------
        PixelText {
            visible: row.kind === "plan" && row.title !== ""
            text: row.title
            font.bold: Theme.plasmaPalette
            color: row.fg
        }
        TextEdit {
            visible: row.kind === "assistant" || row.kind === "plan"
            width: parent.width
            height: visible ? implicitHeight : 0
            text: visible ? row.md : ""
            textFormat: TextEdit.MarkdownText
            readOnly: true
            selectByMouse: true
            persistentSelection: true
            wrapMode: TextEdit.Wrap
            font: row.host ? row.host.monoFont : Qt.application.font
            color: row.fg
            selectionColor: palette.highlight
            selectedTextColor: palette.highlightedText
            onLinkActivated: (url) => {
                if (/^https?:/.test(url)) Qt.openUrlExternally(url);
            }
        }

        // ---- folded rows: thinking, tools, commands, file changes -------------------------
        Item {
            visible: row.foldable
            width: parent.width
            height: visible ? foldHead.implicitHeight + 2 : 0
            PixelText {
                id: foldHead
                anchors { left: parent.left; right: statusText.left; rightMargin: 8 }
                text: (row.open ? "- " : "+ ") + (row.kind === "reasoning" ? "thinking"
                      : row.kind === "file_change" ? "edit " + row.title
                      : row.kind === "command" ? "run " + row.title
                      : row.title)
                elide: Text.ElideRight
                color: row.status === "failed" ? Theme.crit
                       : (row.status === "denied" || row.status === "declined") ? Theme.warn
                       : row.fgDim
            }
            PixelText {
                id: statusText
                anchors.right: parent.right
                text: row.kind === "reasoning" ? (row.status === "running" ? "running" : "")
                      : row.statusWord + (row.detail !== "" && row.kind === "command" ? "  " + row.detail : "")
                color: row.status === "failed" ? Theme.crit : row.fgDim
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: Session.toggle(row.index)
            }
        }
        TextEdit {
            id: foldInput
            visible: row.foldable && row.open && row.kind === "tool" && row.detail !== ""
            width: parent.width
            height: visible ? implicitHeight : 0
            leftPadding: 14
            text: visible ? row.detail : ""
            textFormat: TextEdit.PlainText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
            font: row.host ? row.host.monoFont : Qt.application.font
            color: row.fgDim
            selectionColor: palette.highlight
            selectedTextColor: palette.highlightedText
        }
        TextEdit {
            visible: row.foldable && row.open && row.text !== ""
            width: parent.width
            height: visible ? implicitHeight : 0
            leftPadding: 14
            text: visible ? (row.text.length > 12000 ? "..." + row.text.slice(-12000) : row.text) : ""
            textFormat: TextEdit.PlainText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
            font: row.host ? row.host.monoFont : Qt.application.font
            color: row.kind === "reasoning" ? row.fgDim : row.fg
            selectionColor: palette.highlight
            selectedTextColor: palette.highlightedText
        }

        // ---- approval ---------------------------------------------------------------------------
        PixelText {
            visible: row.kind === "approval" && row.status !== "waiting"
            width: parent.width
            text: row.statusWord + "  " + row.title
            elide: Text.ElideRight
            color: row.status === "denied" ? Theme.warn : row.fgDim
        }
        Rectangle {
            visible: row.kind === "approval" && row.status === "waiting"
            width: parent.width
            height: visible ? apCol.implicitHeight + 12 : 0
            color: "transparent"
            border.color: row.status === "waiting" ? Theme.warn : Theme.border
            border.width: Math.max(1, Theme.ctrlBorder)
            radius: Theme.rounding
            Column {
                id: apCol
                anchors { left: parent.left; right: parent.right; margins: 7
                          verticalCenter: parent.verticalCenter }
                spacing: 5
                PixelText {
                    width: parent.width
                    text: "allow " + row.title
                    font.bold: Theme.plasmaPalette
                    wrapMode: Text.WrapAnywhere
                    color: row.fg
                }
                TextEdit {
                    visible: row.kind === "approval" && row.text !== ""
                    width: parent.width
                    height: visible ? implicitHeight : 0
                    text: visible ? row.md : ""
                    textFormat: TextEdit.MarkdownText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    font: row.host ? row.host.monoFont : Qt.application.font
                    color: row.fg
                }
                PixelText {
                    visible: row.kind === "approval" && row.detail !== ""
                    text: (row.open ? "- " : "+ ") + "input"
                    color: row.fgDim
                    MouseArea { anchors.fill: parent; onClicked: Session.toggle(row.index) }
                }
                TextEdit {
                    visible: row.kind === "approval" && row.open && row.detail !== ""
                    width: parent.width
                    height: visible ? implicitHeight : 0
                    text: visible ? row.detail : ""
                    textFormat: TextEdit.PlainText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    font: row.host ? row.host.monoFont : Qt.application.font
                    color: row.fgDim
                }
                // AskUserQuestion: one button per option of the first question.
                Repeater {
                    model: (row.kind === "approval" && row.status === "waiting" && row.meta
                            && row.meta.questions) ? row.meta.questions : []
                    delegate: Column {
                        id: question
                        required property var modelData
                        spacing: 3
                        PixelText { text: modelData.question || ""; color: row.fg }
                        Flow {
                            width: apCol.width
                            spacing: 6
                            Repeater {
                                model: modelData.options || []
                                delegate: Button {
                                    required property var modelData
                                    text: modelData.label || ""
                                    ToolTip.visible: hovered && (modelData.description || "") !== ""
                                    ToolTip.text: modelData.description || ""
                                    onClicked: {
                                        var a = {};
                                        a[question.modelData.question] = modelData.label;
                                        Session.setAnswers(row.meta.request_id, a);
                                        Session.answer(row.meta.request_id, "allow", "");
                                    }
                                }
                            }
                        }
                    }
                }
                Row {
                    visible: row.kind === "approval" && row.status === "waiting"
                             && !(row.meta && row.meta.questions)
                    spacing: 6
                    Button {
                        text: row.meta && row.meta.tool === "ExitPlanMode" ? "Approve Plan" : "Allow"
                        onClicked: Session.answer(row.meta.request_id, "allow", "")
                    }
                    Button {
                        visible: row.meta && row.meta.can_always === true
                        text: "Allow for Session"
                        onClicked: Session.answer(row.meta.request_id, "always", "")
                    }
                    Button {
                        text: "Deny"
                        onClicked: Session.answer(row.meta.request_id, "deny", "")
                    }
                }
            }
        }

        // ---- errors, notices, images ------------------------------------------------------------------
        TextEdit {
            visible: row.kind === "error"
            width: parent.width
            height: visible ? implicitHeight : 0
            text: visible ? row.text : ""
            textFormat: TextEdit.PlainText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            font: row.host ? row.host.monoFont : Qt.application.font
            color: Theme.crit
        }
        PixelText {
            visible: row.kind === "notice"
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: row.text
            color: row.fgDim
        }
        Image {
            visible: row.kind === "image" && status === Image.Ready
            source: row.kind === "image" && row.meta && row.meta.path ? "file://" + row.meta.path : ""
            width: Math.min(parent.width, sourceSize.width)
            fillMode: Image.PreserveAspectFit
            asynchronous: true
        }
    }
}
