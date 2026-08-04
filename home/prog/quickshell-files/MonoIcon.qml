pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Is an app icon a *monochrome* one — an SVG drawn in `currentColor`?
//
// Our own bespoke app icons (goetia's sigil) are drawn in currentColor so the
// mark IS the live theme's foreground (docs/DESIGN.md §3.1). The compositor's
// titlebar recolours them to the bar's text colour with a librsvg stylesheet
// (`*{color:…}`, ../hyprvtb/vtbDeco.cpp iconTex), which full-colour theme icons
// ignore — so goetia's titlebar icon tracks the theme. The panel's IconImage
// has no such hook: it renders the SVG as-is, resolving currentColor to the
// file's baked `color=` fallback (goetia's is a fixed #cc4400), so the taskbar
// icon did NOT track the theme. TaskCell asks here whether an icon is mono and,
// if so, tints it to the theme through a MultiEffect instead — the panel-side
// equivalent of that stylesheet.
//
// Detection is a one-shot read of the SVG for the string `currentColor`, the
// exact criterion the titlebar's stylesheet relies on. Our bespoke icons live
// in the user hicolor tree (home.file installs them there); breeze/theme icons
// live in the store and are never read, so a full-colour app is a miss and is
// drawn untouched. Cached per name — the SVG is read at most once each.
Singleton {
    id: root

    // iconName -> bool. `undefined` = not yet resolved.
    property var _cache: ({})

    FileView {
        id: probe
        blockLoading: true   // synchronous: text() below is valid right after path is set
        watchChanges: false
        printErrors: false
    }

    function isMono(iconName) {
        if (!iconName)
            return false;
        if (iconName in _cache)
            return _cache[iconName];
        const home = Quickshell.env("HOME") || "";
        probe.path = home + "/.local/share/icons/hicolor/scalable/apps/"
                   + iconName + ".svg";
        const txt = probe.text();
        const mono = !!txt && txt.indexOf("currentColor") !== -1;
        _cache[iconName] = mono;
        return mono;
    }
}
