{ lib, ... }:
{
  # Installs AeroThemePlasma and adds its session to the greeter's list. It does
  # NOT make it the default session — hyprland always is (sys/dsk/plasma.nix).
  # Picking it is a choice made at login, not a rebuild [2026-08-28].
  options.my.aerotheme.enable =
    lib.mkEnableOption "the AeroThemePlasma session as a greeter choice";
}
