{ ... }:

# The systemd user manager's compositor environment is not trustworthy — so
# nothing here is allowed to inherit it.
#
# Hyprland (the compositor itself, not our config) runs `systemctl --user
# import-environment DISPLAY WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE …` at
# every startup and the matching `unset-environment` at clean shutdown. The
# store is manager-global with no owner, so every Hyprland on the box — the
# session AND every nested test compositor an agent starts — writes over the
# last one, and a SIGKILLed nested instance (how the harnesses tear down) leaves
# its dead signature behind for the rest of the login.
#
# Measured on `top` 2026-07-28: the manager named a compositor that had been
# dead for an hour, on wayland-2, while the session ran on wayland-1. Any user
# unit that shells out to `hyprctl` under that env fails to connect and still
# exits 0 — a service that silently does nothing.
#
# `hypr-session-env.sh` resolves the live instance from
# $XDG_RUNTIME_DIR/hypr/*/hyprland.lock instead of believing what it was handed.
# Wrap every unit that needs the compositor in it (see wal.nix); its `--check`
# is what tools/preflight.sh uses to notice the drift, and `--restore` is what
# the nested harnesses call on teardown to repair the D-Bus activation store,
# which unit wrapping cannot reach.
{
  xdg.configFile."scripts/hypr-session-env.sh" = {
    source = ./hypr-env-files/hypr-session-env.sh;
    executable = true;
  };
}
