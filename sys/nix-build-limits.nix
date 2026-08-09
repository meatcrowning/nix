# A nix build may never take the machine down.
#
# `sys/oomd.nix` arms systemd-oomd on the USER slices only, on the reasoning
# that a desktop's runaway is a user process — and that is right about every
# offender it lists. It leaves exactly one hole, which its own comment names
# and does not close: a `nixos-rebuild`'s memory lands in `nix-daemon.service`,
# under `system.slice`, where nothing watches it.
#
# That hole cost a power-cycle on 2026-08-09. An agent's rebuild pulled in
# `ollama-cuda`, which is not in any of our substituters at that revision, so
# nvcc started compiling ggml's CUDA kernels locally — dozens of translation
# units at 2-4 GB each, under `max-jobs = 4` x `cores = 8` (sys/base.nix) —
# while a ComfyUI video run held a float32 VAE on the other side of the same
# 30 GiB. The box livelocked at 13:52 with the compositor unschedulable, which
# under Wayland swallows the Ctrl+Alt+F<n> escape hatch too.
#
# The knobs, and why these and not others:
#
#   MemoryHigh  is the one that matters. It is a THROTTLE, not a kill: past it
#               the build cgroup reclaims hard and swaps against itself (there
#               is 31 GiB of swap) instead of taking pages from his session.
#               A slow build is the correct outcome; a frozen desktop is not.
#   MemoryMax   is the backstop for the case reclaim cannot keep up with. A
#               builder dies and the rebuild fails loudly — recoverable, unlike
#               a livelock.
#   CPU/IOWeight  the freeze is not purely memory: 32 concurrent compilers
#               starve the session of CPU and the swap storm starves it of I/O.
#               Default weight is 100, so this makes builds yield five to one.
#   OOMScoreAdjust  if the kernel killer does fire, it picks a builder rather
#               than the compositor or ComfyUI.
#
# Deliberately NOT done here: arming oomd on `system.slice` wholesale. That
# trades a freeze for a killed system daemon of oomd's choosing, which is the
# trade sys/oomd.nix already refused. This reaches one unit, on purpose.
#
# TWO cgroups, because a build lands in one of two places depending on who
# asked. Measured 2026-08-09 rather than assumed: an unprivileged `nix build`
# goes over the socket and its builders are children of `nix-daemon.service`,
# but ROOT owns the store, so `sudo rebuild-top` builds in-process — its
# builders inherit the CALLER's cgroup, which for an agent is whatever kitty or
# claude scope it happened to be started from. Capping the daemon alone would
# have left the exact rebuild that froze the box uncapped. So `rebuild-top`
# (sys/nixos-rebuild.nix) runs its switch inside a transient scope in the slice
# below, and the two ceilings are kept equal on purpose.
#
# NixOS-only, so `book` does not get it. Its ceilings would be wrong there
# anyway (16 GiB, and it compiles Hyprland from source on every pin bump).
{ ... }:

{
  systemd.services.nix-daemon.serviceConfig = {
    MemoryHigh = "8G";
    MemoryMax = "14G";
    CPUWeight = 20;
    IOWeight = 20;
    OOMScoreAdjust = 500;
  };

  systemd.slices.nix-build = {
    description = "Nix builds started by rebuild-top";
    sliceConfig = {
      MemoryHigh = "8G";
      MemoryMax = "14G";
      CPUWeight = 20;
      IOWeight = 20;
    };
  };
}
