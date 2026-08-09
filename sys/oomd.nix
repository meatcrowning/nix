# systemd-oomd, actually armed.
#
# NixOS enables the daemon by default but leaves every slice on
# `ManagedOOM*=auto`, which means "off unless something opts in" — so on
# 2026-08-08 `top` had oomd running, watching, and empowered to do nothing
# while the machine livelocked under memory pressure and had to be power-cycled
# (the trigger was a ComfyUI video run). comfy-painter briefly carried its own
# MemoryHigh/MemoryMax ceiling as a stopgap (home/prog/painter.nix) but that
# only capped one cgroup's blast radius and did nothing for a nixos-rebuild's
# memory use landing at the same time — this is the actual anti-lockup
# mechanism and the ceiling was removed once it was armed.
#
# The kernel OOM killer is not the safety net people assume it is. It fires on
# ALLOCATION FAILURE, and a box thrashing against swap never quite fails an
# allocation — reclaim keeps inching forward, so the killer stays asleep while
# nothing gets scheduled. That is the freeze: not a crash, a livelock, and it
# takes the compositor with it (under Wayland a Ctrl+Alt+F<n> is delivered to
# Hyprland, so a compositor that cannot be scheduled swallows the one escape
# hatch there was).
#
# oomd watches PRESSURE (PSI) instead, which is what actually rises here, and
# kills the worst descendant cgroup before the machine stops responding.
# `enableUserSlices` scopes that to `user@.slice` and the user-owned slices
# under it — where every one of the offenders lives (comfy-painter, kitty, the
# browser, the agent scopes). The system slice is deliberately left alone: a
# desktop's runaway is a user process, and letting oomd reach system services
# trades a freeze for a killed daemon.
#
# NixOS-only, so `book` does not get this — it is Fedora with home-manager
# layered on, and its oomd policy is Fedora's (which does arm the user slice by
# default, so book was never exposed the same way).
{ ... }:

{
  systemd.oomd = {
    enable = true;
    enableUserSlices = true;
  };
}
