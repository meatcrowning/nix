final: prev: {
  vcv-rack = prev.vcv-rack.overrideAttrs (oldAttrs: {
    patches = builtins.filter (p: !(p ? name && p.name == "fix-segfault-on-linux.patch")) (oldAttrs.patches or []);
  });
}
