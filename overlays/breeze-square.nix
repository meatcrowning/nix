# Square off Breeze: its widget corner radius is a hardcoded compile-time
# constant (kstyle/breezemetrics.h), with no runtime/breezerc setting — so
# the only way to get square corners while keeping Breeze (and its
# kdeglobals-driven, wal-following colours) is to patch that constant to 0
# and rebuild. CheckBox_Radius is defined as Frame_FrameRadius - 1, so it's
# pinned to 0 explicitly rather than left at -1. Merge-override (not
# overrideScope) so only breeze itself rebuilds, not the whole Plasma stack
# that build-depends on it — the style is loaded at runtime, so the patched
# top-level kdePackages.breeze that lands in systemPackages is what matters.
final: prev: {
  kdePackages = prev.kdePackages // {
    breeze = prev.kdePackages.breeze.overrideAttrs (old: {
      postPatch = (old.postPatch or "") + ''
        substituteInPlace kstyle/breezemetrics.h \
          --replace-fail "Frame_FrameRadius = 5" "Frame_FrameRadius = 0" \
          --replace-fail "CheckBox_Radius = Frame_FrameRadius - 1" "CheckBox_Radius = 0"
      '';
    });
  };
}
