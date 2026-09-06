# Oxygen, rebuilt so its chrome follows the SELECTED COLOUR SCHEME.
#
# Why stock Oxygen does not. Two independent mechanisms, and Oxygen fails both:
#
#   1. A Plasma style that ships a `colors` file has its palette read from that
#      file and the system colour scheme is ignored entirely. Breeze ships no
#      such file, which is the whole reason Breeze follows. Oxygen ships one,
#      pinning `BackgroundNormal=40,40,40`.
#   2. Plasma recolours a theme's SVGs by substituting a `<style
#      id="current-color-scheme">` block, which only reaches shapes that
#      reference it by class. Measured on 6.7.4: Breeze has 114 of 122 SVGs
#      stylesheet-aware, Oxygen has 3 of 44.
#
# So deleting `colors` alone is not a fix -- it leaves dark-on-dark art sitting
# on a light scheme. The art has to be converted too, and the conversion is the
# interesting part:
#
#   Oxygen bakes base colour AND gloss into one gradient (#47484b -> #2b2f34 for
#   a button body). Breeze separates them -- a flat `ColorScheme-*` base with
#   the gloss as black/white ALPHA on top, which is why Breeze survives any
#   scheme. `oxyscheme.py` applies that split mechanically: each achromatic
#   gradient becomes a role-filled base plus a derived alpha gloss, wrapped in a
#   <g> that KEEPS THE ORIGINAL ELEMENT ID -- Plasma renders sub-elements by id,
#   so moving the id off the element makes the widget vanish.
#
# What is deliberately NOT converted:
#   - Saturated colour. That is Oxygen's identity; only achromatic paint moves.
#     The threshold is absolute chroma, not relative saturation -- Oxygen's
#     greys are dark and blue-tinted, and relative saturation reads #2b2f34 as
#     17% coloured when its real chroma is 3.5%.
#   - `hint-*` elements. Plasma reads their GEOMETRY as metadata; they are never
#     drawn, and recolouring them is meaningless.
#   - Translucent achromatic fills (fill-opacity < 0.9). A black shadow at 25%
#     already works on any scheme -- it is a shading layer by construction.
#   - The 220 achromatic embedded rasters, same reasoning. The 48 single-hue
#     blue ones ARE converted: they are the focus/hover glows, and a single-hue
#     raster with an alpha falloff becomes a vector gradient whose stops carry a
#     ColorScheme-* class. That also makes them resolution-independent, which
#     8px raster glows were not.
#   - `branding.svgz` and the seven illustrations Breeze also leaves baked.
#
# Both hosts: book runs a Plasma session wearing Oxygen too (see oxygen.nix).
#
# This installs a SEPARATE style and changes nothing on its own -- it is inert
# until picked in System Settings -> Colours & Themes -> Plasma Style.
{ lib, pkgs, ... }:

let
  panel-surface-python = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);
  panel-surface-renderer = pkgs.writeShellScriptBin "plasma-panel-surface-renderer" ''
    # This runs from systemd, outside the Qt wrappers our applications use.
    # Put Oxygen's style plugin in that process explicitly; otherwise Qt falls
    # back to the session's generic style and only the palette happens to match.
    export QT_PLUGIN_PATH=${pkgs.kdePackages.oxygen}/lib/qt-6/plugins:${pkgs.kdePackages.plasma-integration}/lib/qt-6/plugins''${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}
    export XDG_DATA_DIRS=${pkgs.kdePackages.oxygen}/share:${pkgs.kdePackages.plasma-integration}/share''${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}
    export QT_STYLE_OVERRIDE=oxygen
    exec ${panel-surface-python}/bin/python ${./plasma-panel-gradient-files/render-surface.py}
  '';
  # Plasma's FrameSvg tiles its five-pixel centre.  That works for a texture,
  # but cannot represent one gradient shared by a horizontal and vertical
  # panel.  Overlay the stock shell view with a real screen-space surface;
  # retain the invisible FrameSvg beneath it because PanelView reads its mask
  # and margins in C++.
  panel-gradient-view = pkgs.runCommand "plasma-panel-gradient-view"
    { nativeBuildInputs = [ pkgs.perl ]; }
    ''
      mkdir -p $out
      cp -r ${pkgs.kdePackages.plasma-desktop}/share/plasma/shells/org.kde.plasma.desktop/. $out/
      chmod -R u+w $out
      panel_qml=$out/contents/views/Panel.qml
      perl -0pi -e 's/(id: opaqueItem.*?opacity:) root\.panelOpacity/$1 0/s' $panel_qml
      awk -v fragment=${./plasma-panel-gradient-files/Surface.qmlfrag} '
        /^    Keys.onEscapePressed: \{$/ {
          while ((getline line < fragment) > 0) print line
          close(fragment)
          print
          next
        }
        { print }
      ' $panel_qml > $panel_qml.tmp
      mv $panel_qml.tmp $panel_qml
    '';

  oxygen-scheme = pkgs.runCommand "plasma-theme-oxygen-scheme"
    {
      nativeBuildInputs = [ pkgs.python3 ];
      src = "${pkgs.kdePackages.oxygen}/share/plasma/desktoptheme/oxygen";
    }
    ''
      cp ${./plasma-oxygen-scheme-files}/*.py .
      mkdir -p $out
      python3 build-theme.py "$src" "$out"
    '';
in
{
  # ONE directory symlink, not per-file: KPackage rejects per-file symlinks
  # inside a package directory as path traversal.
  home.file.".local/share/plasma/desktoptheme/oxygen-scheme".source = oxygen-scheme;
  home.file.".local/share/plasma/shells/org.kde.plasma.desktop" = {
    source = panel-gradient-view;
    force = true;
  };

  home.packages = [ panel-surface-renderer ];

  # The generated image is a cache of the active Qt style, so refresh it on
  # activation and whenever Plasma's palette/theme settings change.
  home.activation.renderPlasmaPanelSurface = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    ${panel-surface-renderer}/bin/plasma-panel-surface-renderer || true
  '';
  systemd.user.services.plasma-panel-surface = {
    Unit.Description = "render the shared Plasma panel surface";
    Service = {
      Type = "oneshot";
      ExecStart = "${panel-surface-renderer}/bin/plasma-panel-surface-renderer";
    };
  };
  systemd.user.paths.plasma-panel-surface = {
    Unit.Description = "refresh the shared Plasma panel surface after theme changes";
    Path.PathChanged = [
      "%h/.config/kdeglobals"
      "%h/.config/plasmarc"
    ];
    Install.WantedBy = [ "default.target" ];
  };
}
