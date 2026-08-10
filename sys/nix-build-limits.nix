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
#   OOMScoreAdjust  if the kernel killer does fire, it picks a builder rather
#               than the compositor or ComfyUI.
#
# CPUWeight/IOWeight are deliberately NOT set here — the freeze is not purely
# memory (32 concurrent compilers starve the session of CPU, and the swap storm
# starves it of I/O), but a build running alone should have all of both. They
# are applied per-run by rebuild-top on the one path that needs them.
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
# WHAT IS SET HERE IS A BACKSTOP, NOT A THROTTLE. A build that has the machine
# to itself should use it: 20G of headroom is more than anything in this flake
# has ever needed, so these ceilings cost nothing in the normal case and only
# stop a build that has genuinely run away. The real collision — a build and a
# ComfyUI render at once — is not rationed by default, it is put to him:
# `rebuild-top` asks (a critical toast) whether to stop the loaded backends,
# and on yes waits out any render in flight, then stops and masks comfy and/or
# ollama for the duration (tools/heavy-gate.sh, with a notification each way).
# The tight numbers live THERE, applied to that one scope, on the paths where
# the backends stayed up — he said build anyway, he was not at the machine to
# answer, or a render was still running an hour later.
{ pkgs, ... }:

let
  # Equal on both cgroups on purpose: which one a build lands in depends only on
  # who asked, and the machine has the same amount of RAM either way.
  ceiling = {
    MemoryHigh = "20G";
    MemoryMax = "26G";
  };
in
{
  systemd.services.nix-daemon.serviceConfig = ceiling // {
    OOMScoreAdjust = 500;
  };

  systemd.slices.nix-build = {
    description = "Nix builds started by rebuild-top";
    sliceConfig = ceiling;
  };

  # The gate above only reaches `rebuild-top`. An AGENT's own `nix build` goes
  # over the daemon socket, and nothing can suspend comfy on its behalf — it is
  # not a switch, it has no wrapper, and it may be one of several running at
  # once. That is not hypothetical: the ollama packaging bug is being chased by
  # a worker right now, and the way it verifies a fix is by building the exact
  # derivation that froze the box.
  #
  # So for that path the answer IS rationing, but only while there is something
  # to ration against: this watches comfy's queue and tightens the daemon's
  # ceilings for exactly as long as a render is in flight, then puts them back.
  # A build alone still gets the whole machine, which is the rule everywhere
  # else here.
  systemd.services.nix-build-throttle = {
    description = "Tighten nix-daemon's ceilings while ComfyUI is rendering";
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "simple";
      Restart = "always";
      RestartSec = 10;
      # Nothing this unit does may itself be a memory event worth throttling.
      MemoryMax = "64M";
      CPUWeight = 10;
    };
    path = [ pkgs.curl pkgs.systemd pkgs.gnugrep ];
    script = ''
      tight=0
      while :; do
        # A dead or unreachable comfy answers nothing, which is `not rendering`
        # — the same rule tools/heavy-gate.sh uses, for the same reason.
        q=$(curl -sf -m 3 http://127.0.0.1:8188/prompt 2>/dev/null \
            | grep -o '"queue_remaining"[[:space:]]*:[[:space:]]*[0-9]\+' \
            | grep -o '[0-9]\+$' | head -1)
        if [ "''${q:-0}" -gt 0 ] && [ "$tight" = 0 ]; then
          systemctl set-property --runtime nix-daemon.service \
            MemoryHigh=8G MemoryMax=12G CPUWeight=20 IOWeight=20
          echo "comfy is rendering — nix-daemon held to 8G/12G at a fifth weight"
          tight=1
        elif [ "''${q:-0}" -eq 0 ] && [ "$tight" = 1 ]; then
          systemctl set-property --runtime nix-daemon.service \
            MemoryHigh=20G MemoryMax=26G CPUWeight=100 IOWeight=100
          echo "comfy idle — nix-daemon back to the full machine"
          tight=0
        fi
        sleep 15
      done
    '';
  };
}
