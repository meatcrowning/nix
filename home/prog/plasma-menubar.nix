{ pkgs, lib, config, ... }:

# A macOS-style menu bar for the Plasma panel: one that is always there.
#
# Plasma's stock `org.kde.plasma.appmenu` returns HiddenStatus whenever the
# focused window exports no DBus menu (`applets/appmenu/qml/main.qml`, the
# `buttonRepeater.count > 0` branch), and a panel drops a hidden applet
# entirely — so the bar goes blank under Vivaldi, under any GTK/Chromium app,
# and any time focus is on nothing at all. His report, 2026-09-05: *"the text
# will disappear either when vivaldis focused or if im not focused on any
# window"*, wanting instead the macOS behaviour where the bar always names an
# owner and always has menus under it.
#
# Vivaldi cannot be fixed from Vivaldi's side: Chromium has no DBus menu export
# and registers nothing on `com.canonical.AppMenu.Registrar` (checked on top,
# 2026-09-05, with Vivaldi running). So the missing menus have to be authored,
# not imported.
#
# This applet authors ONLY what Plasma has no source for, and sits immediately
# AFTER the stock one. The stock applet vanishes outside a native app menu, so
# this one then takes its place after Kickoff:
#
#   [kickoff]  [ File Edit View … ] [ ]          app exports a menu (stock applet)
#   [kickoff]  [ Window ]                        Vivaldi (ours)
#   [kickoff]  [ File Edit Go Window Help ]      desktop (ours)
#
# Keeping the stock applet is the point — the DBusMenu import, its keyboard
# handling and its search entry stay upstream's, unforked, and a Plasma bump
# cannot strand us on a patched copy of them.
#
# NOTE the whole package directory is deployed as ONE symlink to a store path.
# Per-file symlinks do not work: KPackage canonicalises every file it opens and
# rejects anything resolving outside the package root — the same trap
# home/prog/plasma-notif-gap.nix documents.

let
  pkgId = "org.kde.lam.menubar";

  metadata = builtins.toJSON {
    KPackageStructure = "Plasma/Applet";
    KPlugin = {
      Id = pkgId;
      Name = "Menu Bar";
      Description = "Always-visible app and desktop menus, macOS style";
      Category = "Windows and Tasks";
      Icon = "application-menu";
      EnabledByDefault = true;
      Version = "1.0";
    };
    "X-Plasma-API-Minimum-Version" = "6.0";
  };

  package = pkgs.runCommand pkgId { } ''
    mkdir -p $out/contents/ui
    cp ${pkgs.writeText "metadata.json" metadata} $out/metadata.json
    cp ${./plasma-menubar-files/main.qml} $out/contents/ui/main.qml
  '';

  # QML cannot create a native menu window. This tiny Applet interface does:
  # it owns the QMenu, makes it transient to the panel, and maps it immediately
  # below the selected category. Keeping the menu data/actions in QML leaves
  # the desktop's actual behavior in the readable fallback source.
  nativeInterface = pkgs.stdenv.mkDerivation {
    pname = "plasma-menubar-native-interface";
    version = "1";
    src = ./plasma-menubar-files/native;
    nativeBuildInputs = [
      pkgs.cmake
      pkgs.ninja
      pkgs.kdePackages.extra-cmake-modules
      pkgs.pkg-config
    ];
    buildInputs = [
      pkgs.qt6.qtbase
      pkgs.qt6.qtdeclarative
      pkgs.kdePackages.libplasma
      pkgs.kdePackages.kcoreaddons
    ];
  };
in
{
  home.packages = [ nativeInterface ];
  xdg.dataFile."plasma/plasmoids/${pkgId}".source = package;

  # Installing a plasmoid package never instantiates it, and Plasma has no
  # declarative panel layout. Add exactly one, to whichever panel already holds
  # the stock appmenu applet (that is the bar this belongs beside), falling back
  # to the top panel. The scan makes logins and rebuilds idempotent.
  #
  # The scripting API can only APPEND — there is no reorder in
  # `shell/scripting/containment.h` — so a first-ever install lands it at the
# end of the panel and its place after the appmenu is set once, by hand, in
  # AppletOrder. The one obsolete fixed spacer directly before this applet is
  # removed: it is a blank gutter between Kickoff and the first menu label.
  systemd.user.services.plasma-menubar = {
    Unit = {
      Description = "Add the always-visible menu bar to the Plasma panel";
      After = [ "graphical-session.target" ];
      ConditionEnvironment = "KDE_FULL_SESSION=true";
    };
    Service = {
      Type = "oneshot";
      Environment = [
        "PATH=${lib.makeBinPath [ pkgs.coreutils ]}:${config.home.homeDirectory}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin"
      ];
      ExecStart = pkgs.writeShellScript "plasma-menubar-install" ''
        for attempt in $(seq 1 60); do
          if qdbus org.kde.plasmashell /PlasmaShell \
              org.kde.PlasmaShell.evaluateScript ${lib.escapeShellArg ''
                var present = false;
                var menuPanel = null;
                var menuIndex = -1;
                var beside = -1;
                var top = -1;
                for (var i = 0; i < panelIds.length; ++i) {
                    var panel = panelById(panelIds[i]);
                    if (panel.location === "top" && top < 0) top = panelIds[i];
                    var widgets = panel.widgets();
                    for (var j = 0; j < widgets.length; ++j) {
                        if (widgets[j].type === "${pkgId}") {
                            present = true;
                            menuPanel = panel;
                            menuIndex = j;
                        }
                        if (widgets[j].type === "org.kde.plasma.appmenu") beside = panelIds[i];
                    }
                }
                var target = beside >= 0 ? beside : top;
                if (!present && target >= 0) panelById(target).addWidget("${pkgId}");
                if (present && menuIndex > 0) {
                    var before = menuPanel.widgets()[menuIndex - 1];
                    if (before.type === "org.kde.plasma.panelspacer") before.remove();
                }
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
