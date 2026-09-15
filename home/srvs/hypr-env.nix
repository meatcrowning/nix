{ ... }:

# Nested Hyprland processes can leave the user manager pointing at a dead
# compositor. Wrap compositor-dependent units with hypr-session-env.sh, which
# resolves the live instance from runtime lock files. --check detects drift;
# harness teardown uses --restore to repair the manager and D-Bus environment.
{
  xdg.configFile."scripts/hypr-session-env.sh" = {
    source = ./hypr-env-files/hypr-session-env.sh;
    executable = true;
  };
}
