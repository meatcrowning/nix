{ pkgs, ... }:

# Pulls Plasma's notification popups back up against the panel.
#
# Plasma stacks two independent gaps under a floating panel and never tells you
# about either. Measured in a headless nested Plasma 6.7.4 (1920x1080, bottom
# floating panel 46px thick):
#
#   panel WINDOW           0,1018 1920x62   -> 46 thickness + 8 + 8 float padding
#   panel VISIBLE edge     y=1026
#   notification popup     bottom y=982
#   KWin's maximize area   bottom y=1034
#
# so the popup sat 44px off the panel it spawned from. Both halves are Plasma's:
#
#   - `ShellCorona::_availableScreenRect` subtracts `PanelView::totalThickness()`,
#     i.e. the panel's whole window INCLUDING both floating paddings, so the
#     applet's usable rect already starts 8px clear of the panel. KWin disagrees
#     and reserves the thickness only (1034 vs 1018 above) — maximized windows
#     slide under the float gap, notifications do not.
#   - the notifications applet then adds `popupEdgeDistance`, a flat
#     `Kirigami.Units.gridUnit * 2` (36px at a 10pt UI font) in
#     `applets/notifications/global/Globals.qml`. No setting exposes it, and the
#     KCM's "popup position" only picks a corner.
#
# That applet is compiled into `/usr/lib64/qt6/plugins/plasma/applets/
# org.kde.plasma.notifications.so` as a qrc QML module with no `plugin` line in
# its qmldir, so it cannot be shadowed from a QML import path and cannot be
# edited without rebuilding plasma-workspace.
#
# What CAN reach it: `PlasmaQuick::SharedQmlEngine` keeps ONE process-wide
# QQmlEngine for every applet (`s_engine`, a static weak_ptr), so `Globals` is a
# single instance shared across the shell — and `popupEdgeDistance` is a plain
# writable `property int`, not readonly. A widget of our own, living in the same
# shell, can simply assign it; the assignment kills the gridUnit binding for the
# life of the process.
#
# Verified in that same nested session: popup bottom moved 982 -> 1010, i.e. the
# 44px gap became 16px (our 8 + the panel's own 8, which now reads as one
# margin). Nothing else moved; inter-popup spacing is a separate constant.
#
# The widget has to be ADDED to a panel once per machine — deploying the package
# alone does nothing:
#
#   qdbus org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
#     'panelById(panelIds[0]).addWidget("org.kde.lam.notifgap")'
#
# It draws a 1x1 item and reports PassiveStatus, so it is invisible in a panel
# and lives in the drawer in a system tray. Remove it the same way you would any
# widget. If a future Plasma renames the module the import throws, the retry
# timer keeps failing quietly and you get the stock 36px back — it cannot break
# notifications.

#
# NOTE the whole package directory is deployed as ONE symlink to a store path.
# Per-file symlinks do not work: KPackage canonicalises every file it opens and
# rejects anything that resolves outside the package root, so home-manager's
# usual `/nix/store/...-hm_...metadata.json` link is refused as a "path
# traversal attempt" and the widget fails to load. With the root itself being
# the link, the canonical root IS the store directory and the check passes.

let
  pkgId = "org.kde.lam.notifgap";

  metadata = builtins.toJSON {
    KPackageStructure = "Plasma/Applet";
    KPlugin = {
      Id = pkgId;
      Name = "Notification Popup Gap";
      Description = "Pulls notification popups back up against the panel";
      Category = "Utilities";
      Icon = "preferences-desktop-notification";
      EnabledByDefault = true;
      Version = "1.0";
    };
    "X-Plasma-API-Minimum-Version" = "6.0";
  };

  mainQml = ''
    import QtQuick
    import org.kde.plasma.plasmoid
    import org.kde.plasma.core as PlasmaCore

    PlasmoidItem {
        id: root

        // Distance from the screen rect the applet believes it has, to the
        // popup. Upstream is Kirigami.Units.gridUnit * 2 (36px at a 10pt UI
        // font). 8 matches the floating panel's own margin, so the popup and
        // the panel share one visual inset. This is the only number to tune —
        // note it sets the HORIZONTAL inset from the screen edge too.
        readonly property int edgeDistance: 8

        Plasmoid.status: PlasmaCore.Types.PassiveStatus
        preferredRepresentation: compactRepresentation
        compactRepresentation: Item { implicitWidth: 1; implicitHeight: 1 }

        // The notifications applet's QML module is registered by that applet's
        // own plugin, so it does not exist until the applet has loaded into the
        // shared engine — which may be after us. A static import would make
        // this file fail to compile; build it dynamically and retry instead.
        Timer {
            interval: 500
            repeat: true
            running: true
            onTriggered: {
                try {
                    Qt.createQmlObject(
                        'import QtQuick;'
                        + ' import plasma.applet.org.kde.plasma.notifications as N;'
                        + ' QtObject { function apply(v) { N.Globals.popupEdgeDistance = v } }',
                        root, "notifgap").apply(root.edgeDistance);
                    running = false;
                    console.warn("notifgap: popupEdgeDistance set to " + root.edgeDistance);
                } catch (e) {
                    // notifications applet not up yet — try again next tick
                }
            }
        }
    }
  '';

  package = pkgs.runCommand pkgId { } ''
    mkdir -p $out/contents/ui
    cp ${pkgs.writeText "metadata.json" metadata} $out/metadata.json
    cp ${pkgs.writeText "main.qml" mainQml} $out/contents/ui/main.qml
  '';
in
{
  xdg.dataFile."plasma/plasmoids/${pkgId}".source = package;
}
