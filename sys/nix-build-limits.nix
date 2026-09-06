# A nix build may never take the machine down.
#
# `sys/oomd.nix` covers user slices only; `nixos-rebuild` memory lands in
# `nix-daemon.service` under `system.slice`, where nothing else watches it.
# These limits keep that path from stealing the whole machine: `MemoryHigh`
# throttles first, `MemoryMax` fails loudly if reclaim cannot keep up, and
# `OOMScoreAdjust` makes the kernel pick a builder before the compositor.
#
# The same ceilings are applied to the transient rebuild slice because
# `sudo rebuild-top` builds in-process and its builders inherit the caller's
# cgroup. A build alone should still get the machine; the tighter runtime cap
# is only for the path where a loaded GPU backend is already in flight.
{ pkgs, ... }:

let
  # Equal on both cgroups on purpose: which one a build lands in depends on who
  # asked, and the machine has the same amount of RAM either way.
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

  # The gate above only reaches `rebuild-top`. A plain `nix build` still goes
  # through the daemon socket, so this watcher tightens the daemon ceilings only
  # while ComfyUI has queue work, then restores them. A build alone still gets
  # the whole machine.
  systemd.services.nix-build-throttle = {
    description = "Tighten nix-daemon's ceilings while ComfyUI is rendering";
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "simple";
      Restart = "always";
      RestartSec = 10;
      # Nothing here should itself need throttling.
      MemoryMax = "64M";
      CPUWeight = 10;
    };
    path = [ pkgs.curl pkgs.systemd pkgs.gnugrep ];
    script = ''
      tight=0
      while :; do
        # A dead or unreachable comfy answers nothing, which counts as idle.
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
