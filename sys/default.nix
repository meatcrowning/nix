{ lib, ... }:
let
  # Recursively find all nix files in a directory
  # and return them as a list of paths for 'imports'.
  # This avoids having to manually add every new file to imports.
  umport = path:
    lib.filter
      (p: lib.hasSuffix ".nix" (builtins.toString p) && (builtins.baseNameOf p) != "default.nix")
      (lib.filesystem.listFilesRecursive path);
in
{
  imports = umport ./.;
}
