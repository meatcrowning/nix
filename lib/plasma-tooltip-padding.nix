# Plasma tooltips without the extra inner padding: text-only tooltips (the
# default one and the task manager's launcher/no-thumbnail one) get the same
# inset as window tooltips, which is the theme frame margin alone.
#
# Both QML files are compiled into their libraries, so a theme cannot reach
# them. replaceDependencies swaps the patched builds into the closure without
# rebuilding everything that links libplasma. Book takes top's cross builds
# (lib/air-offload.nix). NixOS module for top and book.
{ pkgs, airOffload ? null, ... }:

let
  kde = pkgs.kdePackages;
  patched = name: patch:
    if airOffload != null then airOffload.${name}
    else kde.${name}.overrideAttrs (old: { patches = (old.patches or [ ]) ++ [ patch ]; });
in
{
  system.replaceDependencies.replacements = [
    {
      oldDependency = kde.libplasma;
      newDependency = patched "libplasma" ../home/prog/plasma-tooltip-padding-libplasma.patch;
    }
    {
      oldDependency = kde.plasma-desktop;
      newDependency = patched "plasma-desktop" ../home/prog/plasma-tooltip-padding-taskmanager.patch;
    }
  ];
}
