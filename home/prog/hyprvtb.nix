{ pkgs, host, inputs, ... }:

let
  # Compositor-side vertical titlebars — see ./hyprvtb/ for the C++ source
  # and why this exists (titlebars locked to windows, which no layer-shell
  # client can do). Built against the exact same hyprland the system runs:
  # the *pinned* `hyprland` flake input (see flake.nix), not pkgs.hyprland,
  # so a stray `nix flake update` can no longer move the compositor out from
  # under the plugin. The plugin refuses to load on a version hash mismatch,
  # so a deliberate pin bump rebuilds this and keeps the two in lockstep.
  #
  # On air, Hyprland comes from Fedora's rpm, not nix (see
  # home/pkgs/desktop/wm.nix), and that build has no git metadata baked in —
  # `hyprctl version` there reports commit "unknown", vs nixpkgs' hyprland
  # embedding the real upstream commit hash. The plugin ABI check is a plain
  # string match against the running compositor's own self-reported hash, so
  # a plugin built against nixpkgs' real hash always gets rejected as a
  # "Version mismatch" on air, even though the library versions otherwise
  # line up exactly. Building hyprvtb against a hyprland whose GIT_* env is
  # forced to "unknown" (matching Fedora's stripped build) makes the two
  # sides agree.
  #
  # Tried running nixpkgs' hyprland directly on air instead (so this
  # override wouldn't be needed) — it crashes on startup, nixpkgs' Mesa
  # lacks working Apple Silicon GBM driver support that Fedora Asahi's
  # patched Mesa has. Reverted; back to this override.
  #
  # AND air needs a different VERSION entirely (the bridge — see flake.nix's
  # `hyprland-air` input and docs/book-hyprvtb-version-bridge.md): Fedora's
  # Fedora rpm is 0.56.2 while top's pin is 0.56.0, and a plugin only loads into the
  # exact compositor version it was built against. So air's plugin builds
  # against the hyprland-air pin (matching Fedora, GIT_* forced to "unknown"
  # to match its stripped rpm) and top's against the main pin. vtbCompat.hpp
  # branches on VTB_HL_056 to compile against both. Keep this bridge until the
  # two hosts share one Hyprland pin.
  hyprlandPinned = inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system}.hyprland;
  hyprlandAir = inputs.hyprland-air.packages.${pkgs.stdenv.hostPlatform.system}.hyprland;

  hyprlandForVtb = if host == "air" then hyprlandAir.overrideAttrs (old: {
    # Hyprland 0.56.2's CMake fallback tries FetchContent for glaze even
    # though the flake already provides the packaged dependency. Keep the
    # build hermetic (and offline) by making that dependency explicit.
    buildInputs = (old.buildInputs or []) ++ [ pkgs.glaze ];
    cmakeFlags = (old.cmakeFlags or []) ++ [
      "-DCMAKE_INCLUDE_PATH=${pkgs.glaze}/include"
    ];
    env = (old.env or { }) // {
      GIT_BRANCH = "unknown";
      GIT_COMMIT_DATE = "unknown";
      GIT_COMMIT_HASH = "unknown";
      GIT_COMMIT_MESSAGE = "unknown";
      GIT_TAG = "unknown";
    };
  }) else hyprlandPinned;

  # nixpkgs' hyprlandPlugins set is itself callPackage'd with a `hyprland`
  # argument (mkHyprlandPlugin builds with *that* hyprland's stdenv), so the
  # pinned compositor has to be threaded through the set, not just handed to
  # ./hyprvtb — otherwise the plugin would compile against nixpkgs' headers.
  hyprvtb = pkgs.callPackage ./hyprvtb {
    hyprland = hyprlandForVtb;
    hyprlandPlugins = pkgs.hyprlandPlugins.override { hyprland = hyprlandForVtb; };
  };
in
{
  # Stable path for hyprland.lua's hl.plugin.load() — the store path moves
  # on every rebuild, the symlink doesn't.
  xdg.configFile."hypr/plugins/libhyprvtb.so".source = "${hyprvtb}/lib/libhyprvtb.so";
}
