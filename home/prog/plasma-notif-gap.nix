{ pkgs, lib, config, ... }:

# Plasma's notification applet adds a fixed 36px popup inset after its available
# screen rect has already accounted for a floating panel. This invisible applet
# shares Plasma's process-wide QML engine and sets the writable inset to 8px;
# the resulting 16px panel-to-popup gap was verified in nested Plasma 6.7.4.
# A renamed upstream module fails harmlessly back to the stock gap.
#
# The service must install the applet into a panel; packaging it is insufficient.
# Deploy the package directory as one store symlink. KPackage rejects the usual
# per-file home-manager symlinks because their canonical targets escape the
# package root.

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

  # Plasma does not have a declarative setting for adding this controller, and
  # merely installing a plasmoid package never instantiates it. Run only in a
  # Plasma session, wait for the shell's scripting API, then add exactly one to
  # the first panel. The scan makes restarts and rebuilds harmless.
  systemd.user.services.plasma-notif-gap = {
    Unit = {
      Description = "Keep Plasma notification popups against the panel";
      After = [ "graphical-session.target" ];
      ConditionEnvironment = "KDE_FULL_SESSION=true";
    };
    Service = {
      Type = "oneshot";
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = pkgs.writeShellScript "plasma-notif-gap-install" ''
        for attempt in $(seq 1 60); do
          if qdbus org.kde.plasmashell /PlasmaShell \
              org.kde.PlasmaShell.evaluateScript ${lib.escapeShellArg ''
                var found = false;
                for (var i = 0; i < panelIds.length; ++i) {
                    var widgets = panelById(panelIds[i]).widgets();
                    for (var j = 0; j < widgets.length; ++j) {
                        if (widgets[j].type === "${pkgId}") found = true;
                    }
                }
                if (!found && panelIds.length > 0)
                    panelById(panelIds[0]).addWidget("${pkgId}");
              ''} >/dev/null 2>&1; then
            exit 0
          fi
          sleep 1
        done
        exit 1
      '';
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };
}
