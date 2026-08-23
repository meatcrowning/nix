{
  pkgs,
  lib,
  ...
}: {
  # Local LLM serving (RTX 5070). Previously a hand-rolled overlay building
  # ollama from a pinned git src with a manually-recorded vendorHash
  # (flake.nix, commented out) — that broke on a lock update and was never
  # backed up, so nothing here has run in a while. nixpkgs ships its own
  # ollama-cuda derivation now; use that instead of re-deriving one, and take
  # the compositor-cachix approach (sys/base.nix substituters) rather than a
  # local CUDA build.
  #
  # The packaging bug is fixed by the `ollama-cuda-overlay` in flake.nix (a
  # backport of nixpkgs 7990e968cb8d, 2026-07-25): this pin's setup-cuda-hook
  # never puts nvcc's dir in CUDAToolkit_ROOT, so the vendored llama.cpp child
  # cmake failed to configure with "CUDA Toolkit not found"
  # (ggml/src/ggml-cuda/CMakeLists.txt:268) — `nix log
  # /nix/store/55pdhdb436bl3idz4lq5n4zhy37kqgaq-ollama-0.32.1.drv`. The overlay
  # is dropped when the nixpkgs input rolls past that commit.
  services.ollama = {
    enable = true;
    package = pkgs.ollama-cuda;
    # The module's default (DynamicUser, /var/lib/ollama/models) left the
    # service reading a near-empty models dir while every pulled model
    # (qwen3.5 variants, gemma4, etc, ~105G) actually lives under
    # ~lam/.ollama/models from years of `ollama pull` run interactively as
    # lam. Point the service at the real data instead of moving 105G;
    # DynamicUser still needs "other" rwx on that tree (chmod, not this file).
    modelsDir = "/home/lam/.ollama/models";

    # ONE model, ONE slot. Both default to more, and both multiply what a single
    # chat costs in memory: a second loaded model is a second full set of
    # weights, and each parallel slot is its own KV cache over a 32k context. He
    # is one person in one window, so neither buys anything and both can cost
    # the machine. This is also what makes `ai-warden`'s "swapping model A for
    # model B frees A first" estimate true rather than hopeful.
    environmentVariables = {
      OLLAMA_MAX_LOADED_MODELS = "1";
      OLLAMA_NUM_PARALLEL = "1";
    };
  };

  # ProtectHome=true (module default) hides /home entirely, so the service
  # can't even traverse to /home/lam/.ollama/models despite ReadWritePaths
  # naming it. "read-only" keeps /home visible (real inodes, so the path
  # exists) while ReadWritePaths still punches a write hole for modelsDir.
  #
  # THE HOLE `sys/oomd.nix` LEAVES OPEN. That module arms systemd-oomd on the
  # USER slices only, on the reasoning that a desktop's runaway is a user
  # process — which is right about comfy-painter, the browser and the agent
  # scopes, and wrong about exactly one thing: ollama is a SYSTEM unit, and it
  # is the single biggest memory holder on the box. Measured 2026-08-22 with
  # nothing unusual running, `memory.current` on this cgroup was 24.7 GiB of
  # 31 for one `qwen3.6:35b-a3b`. Nothing was watching it.
  #
  # A hard `MemoryMax` is the wrong tool here — it would OOM-kill a model
  # mid-load, i.e. turn "big model" into "chatter never works". So:
  #
  #   MemoryHigh  a THROTTLE at 24G, leaving the 6G floor `ai-warden` also
  #               keeps for the desktop. Past it this cgroup reclaims against
  #               itself instead of taking pages from the session.
  #   ManagedOOM* lets oomd reach this ONE system unit under sustained pressure,
  #               which is the freeze precursor. Losing a reply is recoverable;
  #               a livelock takes the compositor with it and needs the power
  #               button (sys/oomd.nix has the mechanism at length).
  systemd.services.ollama.serviceConfig = {
    ProtectHome = lib.mkForce "read-only";
    MemoryAccounting = true;
    MemoryHigh = "24G";
    ManagedOOMMemoryPressure = "kill";
    ManagedOOMMemoryPressureLimit = "60%";
  };

  # oracle's start/stop buttons (apps/oracle/main.py Backend). On top they run
  # `sudo -A systemctl {start,stop} ollama.service` locally; on book, which has
  # no local unit, oracle runs the SAME command over ssh to top
  # (apps/oracle/tools/ollama-tunnel.sh forwards the HTTP port; start/stop go
  # over that ssh) and top askpass cannot prompt on a tty-less ssh. So grant lam
  # passwordless sudo for EXACTLY those two commands — the args are fixed in the
  # sudoers Cmnd, so this cannot be widened into arbitrary systemctl or root.
  security.sudo.extraRules = [{
    users = [ "lam" ];
    commands = [
      { command = "/run/current-system/sw/bin/systemctl start ollama.service";
        options = [ "NOPASSWD" ]; }
      { command = "/run/current-system/sw/bin/systemctl stop ollama.service";
        options = [ "NOPASSWD" ]; }
    ];
  }];
}
