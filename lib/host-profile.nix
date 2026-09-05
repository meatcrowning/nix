{ host }:

# Stable facts shared by the NixOS `top` configuration and the standalone
# `air` home configuration. Keep the flake attribute (`air`) separate from
# the OS hostname (`book`): runtime board files are named after the latter.
let
  isTop = host == "top";
  isBook = host == "air";
in
{
  inherit host isTop isBook;
  hostname = if isBook then "book" else host;
  system = if isTop then "x86_64-linux" else "aarch64-linux";
  repoRoot = "/home/lam/nix";

  # Board services need PySide6 because boardctl imports the complete board
  # module set. The book interpreter is Fedora's system Python, which carries
  # the locally installed PySide6 package.
  boardPython = pkgs:
    if isTop
    then "${pkgs.python3.withPackages (ps: [ ps.pyside6 ])}/bin/python3"
    else "/usr/bin/python3";

  # systemd-user does not inherit the interactive profile reliably. This is
  # intentionally just the common profile tail; callers prepend package paths.
  profilePathTail = home:
    "${home}/.nix-profile/bin:/run/current-system/sw/bin:/etc/profiles/per-user/lam/bin:/usr/bin:/bin";
}
