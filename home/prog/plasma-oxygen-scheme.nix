{ pkgs, ... }:

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
let
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
}
