import QtQuick

// One sender in the notifs page's per-app list — Plasma's per-application
// block (plasmanotifyrc `[Applications][<desktop entry>]`), as a row instead of
// its master/detail pane: the Settings window is 640px wide and its pages are
// one scrolling column, so a second list beside a config pane has nowhere to go.
//
// The row is the app; clicking it discloses that app's rules in an indented
// block with a `border` hairline down its left edge (docs/DESIGN.md §9.1 — the
// rule is subordination, so never `accent`), revealed by clipped growth from
// the row's bottom edge (§6.2). A square pip marks a row whose rules differ
// from the default, exactly as the KCM's dot does.
Item {
    id: root

    // The rule key — Notifications.keyFor(): a desktop entry, an app name, or
    // "@other" for the inherited default.
    property string appKey: ""
    property string label: ""
    // The "@other" row is the default every other sender falls back to, so its
    // own reset target is the shipped default, not an inherited rule.
    property bool isDefault: false

    property bool expanded: false

    // This app's stored rule, or an empty one. Only divergences are stored, so
    // every field falls back the same way Notifications.ruleFor() resolves it.
    readonly property var rule: (SettingsStore.d.notifRules || {})[appKey] || ({})
    readonly property var inherited: root.isDefault ? ({}) : ((SettingsStore.d.notifRules || {})["@other"] || ({}))
    readonly property bool customised: Object.keys(root.rule).length > 0

    function _eff(field) {
        if (root.rule[field] !== undefined)
            return root.rule[field];
        if (!root.isDefault && root.inherited[field] !== undefined)
            return root.inherited[field];
        return field === "dnd" ? false : true;
    }

    // Rules are rewritten wholesale, never mutated: SettingsStore diffs each
    // key by JSON.stringify against its last-seen-on-disk snapshot, so editing
    // the object it handed back would change both sides of that comparison and
    // the save would find nothing to write.
    function setField(field, value) {
        const rules = SettingsStore.d.notifRules || {};
        const next = {};
        for (const k in rules) {
            const r = rules[k], copy = {};
            for (const f in r) copy[f] = r[f];
            next[k] = copy;
        }
        const mine = next[root.appKey] || (next[root.appKey] = {});
        mine[field] = value;
        SettingsStore.d.notifRules = next;
        SettingsStore.save();
    }

    function clearRule() {
        const rules = SettingsStore.d.notifRules || {};
        const next = {};
        for (const k in rules) if (k !== root.appKey) next[k] = rules[k];
        SettingsStore.d.notifRules = next;
        SettingsStore.save();
    }

    width: parent ? parent.width : 480
    implicitHeight: head.height + body.height

    // ---- the row ----------------------------------------------------------
    Rectangle {
        id: head
        width: parent.width
        height: 26
        color: ma.containsMouse ? Theme.bgAlt : "transparent"

        // The disclosure state, said in the one glyph the pixel font is sure
        // to have. Rotating it would be a second motion for the same reveal.
        PixelText {
            id: caret
            anchors { left: parent.left; leftMargin: 4; verticalCenter: parent.verticalCenter }
            text: root.expanded ? "-" : "+"
            color: Theme.textDim
        }
        PixelText {
            anchors {
                left: caret.right; leftMargin: 8
                right: pip.left; rightMargin: 8
                verticalCenter: parent.verticalCenter
            }
            text: root.label
            color: root.isDefault ? Theme.textDim : Theme.text
            elide: Text.ElideRight
        }
        // Differs-from-default marker. Square, like everything else here.
        Rectangle {
            id: pip
            anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
            width: 6
            height: 6
            radius: 0
            visible: root.customised
            color: Theme.accent
        }

        MouseArea {
            id: ma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.expanded = !root.expanded
        }
    }

    // ---- its rules, indented under it -------------------------------------
    Item {
        id: body
        anchors.top: head.bottom
        width: parent.width
        height: root.expanded ? inner.implicitHeight + 8 : 0
        clip: true

        Behavior on height {
            NumberAnimation { duration: ViewMode.ms(180); easing.type: ViewMode.slideEasing }
        }

        // The subordination hairline, one 8px step in from the row's text.
        Rectangle {
            anchors { left: parent.left; leftMargin: 12; top: parent.top; bottom: parent.bottom }
            width: 1
            color: Theme.border
        }

        Column {
            id: inner
            anchors { left: parent.left; leftMargin: 20; right: parent.right; top: parent.top; topMargin: 4 }
            spacing: 2

            SetRow {
                label: "show popups"
                desc: root.isDefault ? "the default for a sender with no rule of its own" : ""
                SetToggle {
                    checked: root._eff("popup")
                    onToggled: (v) => root.setField("popup", v)
                }
            }
            SetRow {
                label: "show in do not disturb"
                SetToggle {
                    checked: root._eff("dnd")
                    onToggled: (v) => root.setField("dnd", v)
                }
            }
            SetRow {
                label: "play a sound"
                SetToggle {
                    checked: root._eff("sound")
                    onToggled: (v) => root.setField("sound", v)
                }
            }
            SetRow {
                label: "rule"
                desc: root.customised ? "" : (root.isDefault ? "the shipped default" : "inherited")
                PixelText {
                    text: root.customised ? "[ reset ]" : "[ default ]"
                    color: root.customised ? (rma.containsMouse ? Theme.accent : Theme.textDim) : Theme.dim
                    MouseArea {
                        id: rma
                        anchors.fill: parent
                        anchors.margins: -4
                        enabled: root.customised
                        hoverEnabled: root.customised
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.clearRule()
                    }
                }
            }
        }
    }
}
