{ pkgs, host, ... }:

let
  # Compositor-side vertical titlebars — see ./hyprvtb/ for the C++ source
  # and why this exists (titlebars locked to windows, which no layer-shell
  # client can do). Built against the same nixpkgs hyprland the system runs;
  # the plugin refuses to load on a version hash mismatch, so after a
  # hyprland bump this rebuilds and keeps working automatically.
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
  pkgsForVtb = if host == "air" then pkgs.extend (final: prev: {
    hyprland = prev.hyprland.overrideAttrs (old: {
      env = (old.env or { }) // {
        GIT_BRANCH = "unknown";
        GIT_COMMIT_DATE = "unknown";
        GIT_COMMIT_HASH = "unknown";
        GIT_COMMIT_MESSAGE = "unknown";
        GIT_TAG = "unknown";
      };
    });
  }) else pkgs;
  hyprvtb = pkgsForVtb.callPackage ./hyprvtb { };
in
{
  # Stable path for hyprland.lua's hl.plugin.load() — the store path moves
  # on every rebuild, the symlink doesn't.
  xdg.configFile."hypr/plugins/libhyprvtb.so".source = "${hyprvtb}/lib/libhyprvtb.so";
}
