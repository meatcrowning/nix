import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// The browse pane: the same strip of window showing one of three things, picked
// by the titlebar button that is lit.
//
//   files    every markdown file around the open document (its git root, else
//            its directory) — a directory of fifteen wants a list
//   outline  this document's headings — a 2300-line file with 23 sections wants
//            an outline, and the heading the viewport is inside is marked, so
//            it doubles as a position readout
//   results  cross-document search hits, file by file
//
// It carries NO title of its own (docs/DESIGN.md §5.4 — the content identifies
// itself, and the lit titlebar cell already says which mode this is). Rows are
// one font cell tall with no padding, hover fills `Theme.highlight`, and the
// current row keeps the 2px accent gutter §9.1 gives it.
Item {
    id: side

    property string mode: "outline"       // files | outline | results
    property var files: []
    property var outline: []
    property var results: []
    property string currentPath: ""
    property int section: -1              // outline row the viewport is inside
    property string query: ""
    property real cellW: 8
    property bool winActive: true

    signal openDoc(string path)
    signal openResult(string path)
    signal jumpIndex(int index)

    // The three modes flattened into one row model, so there is one list, one
    // delegate and one set of row mechanics rather than three.
    readonly property var rows: {
        var out = [], i, j;
        if (mode === "files") {
            for (i = 0; i < files.length; i++)
                out.push({ kind: "file", label: files[i].rel, path: files[i].path,
                           indent: 0, dim: false });
        } else if (mode === "outline") {
            for (i = 0; i < outline.length; i++)
                out.push({ kind: "head", label: outline[i].text, index: outline[i].index,
                           row: i, indent: Math.max(0, outline[i].level - 1) * 2,
                           dim: outline[i].level > 2 });
        } else {
            for (i = 0; i < results.length; i++) {
                var r = results[i];
                out.push({ kind: "hitfile", label: r.rel + "  " + r.hits,
                           path: r.path, indent: 0, dim: false });
                for (j = 0; j < r.lines.length; j++)
                    out.push({ kind: "hitline", label: r.lines[j].n + "  " + r.lines[j].text,
                               path: r.path, indent: 2, dim: true });
            }
        }
        return out;
    }

    // The empty state is a sentence, in the one grammar this app uses for all
    // three (docs/DESIGN.md §19.2 item 9 records that the desktop has three).
    readonly property string emptyText:
        mode === "files" ? "no .md files here"
      : mode === "outline" ? "no headings"
      : query.length > 1 ? "no matches" : "type to search"

    Rectangle {
        anchors.fill: parent
        color: Theme.bg
    }

    PixelText {
        anchors.centerIn: parent
        visible: side.rows.length === 0
        color: Theme.dim              // "empty & unviewed" — the token's own job
        text: side.emptyText
        elide: Text.ElideRight
        width: parent.width - 12
        horizontalAlignment: Text.AlignHCenter
    }

    KineticListView {
        id: list
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 2
        clip: true
        model: side.rows
        ScrollBar.vertical: VScroll {}      // qmlcommon/, docs/DESIGN.md 9.2

        delegate: Item {
            id: row
            required property var modelData
            required property int index
            width: list.width - 4
            height: Theme.fontSize

            readonly property bool isCurrent:
                (modelData.kind === "head" && modelData.row === side.section)
                || ((modelData.kind === "file" || modelData.kind === "hitfile")
                    && modelData.path === side.currentPath)

            Rectangle {
                anchors.fill: parent
                color: ma.containsMouse ? Theme.highlight
                     : row.isCurrent ? Theme.highlight : "transparent"
            }
            Rectangle {               // the current row's accent gutter
                width: 2
                height: parent.height
                visible: row.isCurrent
                color: side.winActive ? Theme.accent : Theme.inactive
            }

            PixelText {
                x: 4 + row.modelData.indent * side.cellW
                width: parent.width - x - 2
                height: parent.height
                elide: Text.ElideRight
                text: row.modelData.label
                color: !side.winActive ? Theme.inactive
                     : row.isCurrent ? Theme.accent
                     : row.modelData.dim ? Theme.textDim : Theme.text
            }

            MouseArea {
                id: ma
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    var d = row.modelData;
                    if (d.kind === "head") side.jumpIndex(d.index);
                    else if (d.kind === "file") side.openDoc(d.path);
                    else side.openResult(d.path);
                }
            }
        }
    }

    // The divider between the sidebar and the document. 1px at rest, accent
    // while grabbed — and it tracks the pointer exactly, with no easing (§6.4).
    Rectangle {
        anchors.right: parent.right
        width: 1
        height: parent.height
        color: Theme.border
    }

}
