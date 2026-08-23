import QtQuick
import QtQuick.Controls.Basic
import "../../qmlcommon"

// The smart-playlist rule editor: a modal over the playlists view (the modal
// spec is docs/DESIGN.md §7.2 — 0.5 black scrim, click-outside cancels, box in
// Theme.bg + windowBorder, 12px margins, right-aligned button row).
//
// A rule is {field, op, value}; the vocabulary is main.py's (SMART_FIELDS,
// SMART_OPS, SMART_SORTS) and is asked for at open rather than restated here,
// so adding a field there is enough to make it appear in these menus.
//
// Three things about the state, each learned from the shape of the thing:
//
//  * The editor holds a WORKING COPY and the store never sees a keystroke.
//    Cancel is then free — there is no draft to roll back — and the live list
//    behind the modal keeps showing what it currently is, not what it might
//    become.
//  * `rules` is reassigned (`rules = rules.slice()`) only when a row's SHAPE
//    changes (a different field or operator, a row added or removed), because
//    that is what rebuilds the delegates. A value edit mutates in place and
//    reassigns nothing: rebuilding on every keystroke would take the focus out
//    of the text box being typed into after the first character.
//  * The match count is the one honest readout that the rules do something
//    (§10.1), so it is recomputed — debounced — on every edit, off the same
//    SQL the saved list will run.
Item {
    id: root
    property color fgText: Theme.text
    property color fgDim: Theme.textDim
    property color fgAccent: Theme.accent

    signal saved(string name)

    visible: false

    // THE SESSION, and the one number the two faces cannot share. Every row
    // here was sized to the pixel face's 24px control; under Plasma the style
    // owns those heights (Oxygen's field and combo are both taller), and a row
    // pinned to 24 crops the frame it is drawing. `ctrlH` is 0 outside a Plasma
    // session, so every `Math.max(<the old literal>, root.ctrlH)` below is
    // exactly the old literal there and the Hyprland layout cannot move.
    readonly property bool plasma: (typeof DeskStyle !== "undefined" && DeskStyle)
                                   ? DeskStyle.plasma === true : false
    readonly property int ctrlH: root.plasma
        ? Math.max(hProbe.implicitHeight, pProbe.implicitHeight) : 0
    // Measured, not tabulated: the style's metrics are the style's, and the
    // `+plasma` twins are the only things that know them. Invisible, never laid
    // out, and free in the session that ignores them.
    EditField { id: hProbe; visible: false }
    SelectButton { id: pProbe; visible: false }

    // ---- working copy ----
    property string origName: ""     // "" = creating; else the list being replaced
    property string listName: ""
    property string matchMode: "all"
    property var rules: []
    property string sortKey: "artist"
    property bool descending: false
    property int limitN: 0
    property int matchCount: 0

    function edit(name) {
        var spec = Library.smartSpec(name);
        if (!spec || !spec.name)
            return;                  // nothing selected — nothing to edit
        _load(spec, name);
    }

    function createNew() {
        _load(Library.newSmartSpec(), "");
    }

    function _load(spec, from) {
        origName = from;
        listName = spec.name;
        matchMode = spec.match;
        // Copy every rule out of the spec: the object handed over by the
        // bridge is a fresh conversion, but treating it as ours to mutate is
        // exactly the habit that makes a cancel leave changes behind.
        var rs = [];
        for (var i = 0; i < spec.rules.length; i++) {
            var r = spec.rules[i];
            rs.push({ field: r.field, op: r.op, value: r.value });
        }
        rules = rs;
        sortKey = spec.sort;
        descending = spec.desc;
        limitN = spec.limit;
        visible = true;
        recount();
        nameField.focusInput();
        nameField.selectAll();
    }

    function specNow() {
        return { name: listName, match: matchMode, rules: rules,
                 sort: sortKey, desc: descending, limit: limitN };
    }

    function save() {
        var name = Library.saveSmart(specNow(), origName);
        visible = false;
        root.saved(name);
    }

    function cancel() { visible = false; }

    // ---- rule edits ----

    function defaultValue(field) {
        switch (Library.smartFieldKind(field)) {
        case "text":    return "";
        case "bool":    return true;
        case "stars":   return 4;
        case "minutes": return 5;
        case "date":    return 30;
        default:        return 1;
        }
    }

    function setField(i, field) {
        var r = rules[i];
        r.field = field;
        var ops = Library.smartOps(field);
        if (ops.indexOf(r.op) < 0)
            r.op = ops[0];
        r.value = defaultValue(field);
        rules = rules.slice();
        recount();
    }

    function setOp(i, op) {
        var r = rules[i];
        r.op = op;
        if (Library.smartOpTakesValue(op) && r.value === undefined)
            r.value = defaultValue(r.field);
        rules = rules.slice();
        recount();
    }

    // `rebuild` false is the typed case: mutate in place and reassign nothing,
    // so the TextInput being typed into is not destroyed and rebuilt after
    // every character. The clicked controls (the stars, yes/no) pass true —
    // they have no focus to lose, and their value is a BINDING onto the rule,
    // which only a reassign re-evaluates.
    function setValue(i, v, rebuild) {
        rules[i].value = v;
        if (rebuild)
            rules = rules.slice();
        recount();
    }

    // A picker reports where it is in scene coordinates; the menu lives in
    // ours. Nothing else in this file may assume the two are the same.
    function openMenu(sceneX, sceneY, items) {
        var p = root.mapFromItem(null, sceneX, sceneY);
        pickMenu.open(p.x, p.y, items);
    }

    function addRule() {
        rules.push({ field: "artist", op: "contains", value: "" });
        rules = rules.slice();
        recount();
    }

    function removeRule(i) {
        rules.splice(i, 1);
        rules = rules.slice();
        recount();
    }

    function recount() { countTimer.restart(); }

    Timer {
        id: countTimer
        interval: 160          // a keystroke's worth; the query is ~11k rows
        onTriggered: root.matchCount = Library.smartPreviewCount(root.specNow())
    }

    // ---- labels (the vocabulary lives in main.py; this only renders it) ----

    function fieldLabel(key) {
        var f = Library.smartFields();
        for (var i = 0; i < f.length; i++)
            if (f[i].key === key) return f[i].label;
        return key;
    }

    function sortLabel(key) {
        var s = Library.smartSorts();
        for (var i = 0; i < s.length; i++)
            if (s[i].key === key) return s[i].label;
        return key;
    }

    Motion { id: motion }

    // Scrim: click outside cancels (§7.2), and it swallows everything so a
    // click never reaches the list behind.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.5)
        MouseArea { anchors.fill: parent; onClicked: root.cancel() }
    }

    SheetFrame {
        id: box
        anchors.centerIn: parent
        width: Math.min(460, root.width - 16)
        height: Math.min(head.height + body.contentHeight + foot.height + 24,
                         root.height - 16)

        MouseArea { anchors.fill: parent }   // swallow: not an outside click

        // rule rows go two-line below this, so the value box keeps a usable
        // width on book's screen (§5.6 — layouts must survive the small one).
        readonly property bool narrow: width < 380
        readonly property int inner: width - 24

        // ---- header ----
        Item {
            id: head
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: 12 }
            height: Math.max(20, root.ctrlH)
            PixelText {
                anchors.verticalCenter: parent.verticalCenter
                text: root.origName === "" ? "new smart playlist" : "edit smart playlist"
                color: root.fgAccent
            }
            HeaderButton {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                label: "x"
                iconName: "window-close"; iconOnly: true
                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                onClicked: root.cancel()
            }
        }

        Rectangle {
            id: headRule
            anchors { top: head.bottom; topMargin: 8; left: parent.left; right: parent.right }
            anchors.leftMargin: 1; anchors.rightMargin: 1
            height: 1
            color: Theme.border
        }

        // ---- body ----
        KineticFlickable {
            id: body
            anchors { top: headRule.bottom; bottom: footRule.top;
                      left: parent.left; right: parent.right; margins: 12 }
            clip: true
            contentHeight: col.implicitHeight
            ScrollBar.vertical: VScroll { visible: body.contentHeight > body.height }

            Column {
                id: col
                width: box.inner
                spacing: 8

                // ---- name ----
                EditField {
                    id: nameField
                    width: parent.width
                    placeholderText: "playlist name"
                    maximumLength: 64
                    fgText: root.fgText; fgAccent: root.fgAccent
                    text: root.listName
                    // `textEdited`, not a `text` watcher: the binding above
                    // writes this box whenever the working copy is loaded, and
                    // a two-way watcher would answer that write with a write of
                    // its own.
                    onTextEdited: root.listName = text
                    onEscaped: root.cancel()
                    onAccepted: root.save()
                }

                // ---- match all / any ----
                Row {
                    spacing: 6
                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "match"
                        color: root.fgDim
                    }
                    HeaderButton {
                        label: root.matchMode === "all" ? "all" : "any"
                        lit: true
                        fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                        onClicked: {
                            root.matchMode = root.matchMode === "all" ? "any" : "all";
                            root.recount();
                        }
                    }
                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "of these rules:"
                        color: root.fgDim
                    }
                }

                // ---- rules ----
                Repeater {
                    model: root.rules

                    delegate: Item {
                        id: ruleRow
                        required property int index
                        required property var modelData
                        readonly property string kind: Library.smartFieldKind(modelData.field)
                        readonly property bool hasValue: Library.smartOpTakesValue(modelData.op)

                        width: col.width
                        height: box.narrow && hasValue
                              ? Math.max(50, root.ctrlH * 2 + 2)
                              : Math.max(24, root.ctrlH)

                        // field + operator, always on the first line
                        Row {
                            id: pickers
                            anchors.left: parent.left
                            anchors.top: parent.top
                            height: Math.max(24, root.ctrlH)
                            spacing: 4

                            SelectButton {
                                width: box.narrow ? 100 : 110
                                label: root.fieldLabel(ruleRow.modelData.field)
                                options: root._opts(Library.smartFields())
                                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                                onPicked: function (x, y, items) { root.openMenu(x, y, items); }
                                onChose: function (k) { root.setField(ruleRow.index, k); }
                            }
                            SelectButton {
                                width: box.narrow ? 110 : 120
                                label: ruleRow.modelData.op
                                options: Library.smartOps(ruleRow.modelData.field)
                                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                                onPicked: function (x, y, items) { root.openMenu(x, y, items); }
                                onChose: function (o) { root.setOp(ruleRow.index, o); }
                            }
                        }

                        // value: beside the pickers when there is room, under
                        // them when there is not
                        Item {
                            id: valueBox
                            visible: ruleRow.hasValue
                            anchors.left: box.narrow ? parent.left : pickers.right
                            anchors.leftMargin: box.narrow ? 0 : 4
                            anchors.top: box.narrow ? pickers.bottom : parent.top
                            anchors.topMargin: box.narrow ? 2 : 0
                            anchors.right: parent.right
                            anchors.rightMargin: box.narrow ? 0 : 22
                            height: Math.max(24, root.ctrlH)

                            // text / number entry
                            EditField {
                                id: valueField
                                anchors.fill: parent
                                anchors.rightMargin: unit.visible ? unit.width + 4 : 0
                                visible: ruleRow.kind === "text" || ruleRow.kind === "count"
                                         || ruleRow.kind === "minutes" || ruleRow.kind === "date"
                                fgText: root.fgText; fgAccent: root.fgAccent
                                // A number field that accepts letters would
                                // silently store 0 (§10.2: refuse visibly).
                                validator: ruleRow.kind === "text" ? null : doubleVal
                                text: ruleRow.modelData.value === undefined
                                      ? "" : String(ruleRow.modelData.value)
                                onTextEdited: root.setValue(
                                    ruleRow.index,
                                    ruleRow.kind === "text" ? text : Number(text || 0))
                                onEscaped: root.cancel()
                                onAccepted: root.save()
                            }
                            PixelText {
                                id: unit
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                visible: ruleRow.kind === "minutes" || ruleRow.kind === "date"
                                text: ruleRow.kind === "date" ? "days" : "min"
                                color: root.fgDim
                            }

                            // stars
                            Stars {
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                visible: ruleRow.kind === "stars"
                                fgAccent: root.fgAccent
                                rating: Number(ruleRow.modelData.value || 0) / 5
                                // Stars sends -1 for "clicked the current
                                // rating again", which clears a track's rating.
                                // A RULE has no unrated state — that is what the
                                // "is unset" operator is for — so a clear here
                                // is read as picking that same value again.
                                onRated: function (v) {
                                    root.setValue(ruleRow.index,
                                                  v < 0 ? Number(ruleRow.modelData.value || 0)
                                                        : Math.round(v * 5), true);
                                }
                            }

                            // yes / no
                            HeaderButton {
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                visible: ruleRow.kind === "bool"
                                label: ruleRow.modelData.value ? "yes" : "no"
                                lit: ruleRow.modelData.value === true
                                fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                                onClicked: root.setValue(ruleRow.index,
                                                         !ruleRow.modelData.value, true)
                            }
                        }

                        HeaderButton {
                            anchors.right: parent.right
                            anchors.verticalCenter: pickers.verticalCenter
                            label: "x"
                            iconName: "list-remove"; iconOnly: true
                            fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                            onClicked: root.removeRule(ruleRow.index)
                        }
                    }
                }

                HeaderButton {
                    label: "+ rule"
                    plainLabel: "add rule"; iconName: "list-add"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: root.addRule()
                }

                Rectangle { width: parent.width; height: 1; color: Theme.border }

                // ---- sort ----
                Row {
                    spacing: 6
                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "sort by"
                        color: root.fgDim
                    }
                    SelectButton {
                        width: 110
                        label: root.sortLabel(root.sortKey)
                        options: root._opts(Library.smartSorts())
                        fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                        onPicked: function (x, y, items) { root.openMenu(x, y, items); }
                        onChose: function (k) { root.sortKey = k; }
                    }
                    HeaderButton {
                        // Meaningless for a random order, and a control that
                        // does nothing is not drawn (§1, §10.1).
                        visible: root.sortKey !== "random"
                        label: root.descending ? "high to low" : "low to high"
                        fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                        onClicked: root.descending = !root.descending
                    }
                }

                // ---- limit ----
                Row {
                    spacing: 6
                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "limit to"
                        color: root.fgDim
                    }
                    EditField {
                        id: limitField
                        width: 60
                        fgText: root.fgText; fgAccent: root.fgAccent
                        validator: IntValidator { bottom: 0; top: 100000 }
                        text: String(root.limitN)
                        onTextEdited: { root.limitN = Number(text || 0); root.recount(); }
                        onEscaped: root.cancel()
                        onAccepted: root.save()
                    }
                    PixelText {
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.limitN > 0 ? "tracks" : "tracks (0 = no limit)"
                        color: root.fgDim
                    }
                }
            }
        }

        Rectangle {
            id: footRule
            anchors { bottom: foot.top; bottomMargin: 8; left: parent.left; right: parent.right }
            anchors.leftMargin: 1; anchors.rightMargin: 1
            height: 1
            color: Theme.border
        }

        // ---- footer: the live count, then the buttons ----
        Item {
            id: foot
            anchors { bottom: parent.bottom; left: parent.left; right: parent.right; margins: 12 }
            height: Math.max(20, root.ctrlH)
            PixelText {
                anchors.verticalCenter: parent.verticalCenter
                text: root.matchCount === 1 ? "1 track matches"
                                            : root.matchCount + " tracks match"
                color: root.matchCount > 0 ? root.fgDim : Theme.dim
            }
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                HeaderButton {
                    label: "cancel"
                    iconName: "dialog-cancel"
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: root.cancel()
                }
                HeaderButton {
                    label: "save"
                    iconName: "document-save"
                    lit: true
                    fgText: root.fgText; fgDim: root.fgDim; fgAccent: root.fgAccent
                    onClicked: root.save()
                }
            }
        }
    }

    DoubleValidator { id: doubleVal; bottom: 0; decimals: 2; notation: DoubleValidator.StandardNotation }

    // One menu instance for every picker in the editor — §7.3, one popup at a
    // time. It fills the editor (which fills the window), so CtxMenu clamps
    // against the whole window rather than the row the button sits in.
    CtxMenu { id: pickMenu; anchors.fill: parent }

    // main.py's `[{label, key}]` vocabularies as SelectButton `options`
    // (`[{label, value}]`). It replaces `_pick`, which built a menu entry with a
    // closure per row: the choices are declared on the button now, so the
    // Plasma face can be the KStyle's own ComboBox (SelectButton.qml).
    function _opts(list) {
        var out = [];
        for (var i = 0; i < (list || []).length; i++)
            out.push({ label: list[i].label, value: list[i].key });
        return out;
    }

    Keys.onEscapePressed: root.cancel()
}
