{ host, os ? (if host == "air" then "fedora" else "nixos") }:

# Stable facts shared by the NixOS configurations and the standalone `air`
# home configuration. Keep the flake attribute (`air`) separate from the OS
# hostname (`book`): runtime board files are named after the latter.
# isBook is the machine; isFedora is the OS under it. Fedora-only paths
# (/usr/bin/python3, Fedora's toolchain and plugins) key on isFedora.
let
  isTop = host == "top";
  isBook = host == "air";
  isFedora = os == "fedora";
in
{
  inherit host os isTop isBook isFedora;
  hostname = if isBook then "book" else host;
  system = if isTop then "x86_64-linux" else "aarch64-linux";
  repoRoot = "/home/lam/nix";

  # Board services need PySide6 because boardctl imports the complete board
  # module set. Fedora's system Python carries the locally installed PySide6.
  boardPython = pkgs:
    if !isFedora
    then "${pkgs.python3.withPackages (ps: [ ps.pyside6 ])}/bin/python3"
    else "/usr/bin/python3";

  # Interpreter for the live-source apps on book. Fedora's carries PySide6 and
  # the rest from dnf/pip; NixOS book uses the same set from nixpkgs.
  bookPython = pkgs:
    if isFedora
    then "/usr/bin/python3"
    else "${pkgs.python3.withPackages (ps: [ ps.pyside6 ps.pillow ps.mutagen ps.pygobject3 ])}/bin/python3";

  # systemd-user does not inherit the interactive profile reliably. This is
  # intentionally just the common profile tail; callers prepend package paths.
  profilePathTail = home:
    "${home}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin";
}
