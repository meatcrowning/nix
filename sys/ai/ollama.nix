{
  pkgs,
  lib,
  ...
}: let
  # The Qwen3.8 compatibility router is unfinished. Keep its implementation in
  # the worktree without putting its custom llama.cpp/CUDA build in the system
  # closure until the protocol and packaging work is resumed.
  qwen38ShimEnabled = false;

  # A deliberately narrow llama.cpp fork for the one GGUF Ollama 0.32 cannot
  # parse.  This revision is after upstream's Q2_0 CPU + CUDA merge and carries
  # Qwen3.8's chat template, reasoning stream and tool-call parser.  Build only
  # GB205's native sm_120 kernels: this package never runs on book and compiling
  # every CUDA generation would turn a small compatibility backend into a much
  # larger rebuild.
  qwen38Llama = (pkgs.llama-cpp.override {
    cudaSupport = true;
    cpuArchDynamicDispatch = false;
  }).overrideAttrs (old: {
    version = "qwen38-6703d78";
    src = pkgs.fetchFromGitHub {
      owner = "ggml-org";
      repo = "llama.cpp";
      rev = "6703d7894c70e8b076ce4608157d056e42e6889c";
      hash = "sha256-bzDQl51ZJ6sEmw3A8tOahL8Tx/pQkq+5OBnk8rldwno=";
      leaveDotGit = true;
      postFetch = ''
        git -C "$out" rev-parse --short HEAD > "$out/COMMIT"
        find "$out" -name .git -print0 | xargs -0 rm -rf
      '';
    };
    # package-lock.json is unchanged from nixpkgs' b10408 package.
    npmDepsHash = "sha256-2Q7XhaLAArmviOLdQsNbYTfdyDE5pW9lR26cRHEVl9k=";
    cmakeFlags =
      builtins.filter
        (flag: !(lib.hasPrefix "-DCMAKE_CUDA_ARCHITECTURES" flag))
        old.cmakeFlags
      ++ [ "-DCMAKE_CUDA_ARCHITECTURES:STRING=120" ];
  });

  qwen38Shim = pkgs.writeText "qwen38-ollama-shim.py"
    (builtins.readFile ../../apps/oracle/tools/qwen38-ollama-shim.py);
in {
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
    #
    # OLLAMA_KEEP_ALIVE: FEWER TEARDOWNS, because the teardown is what crashed
    # the machine. On 2026-08-24 top livelocked and had to be reset; the cause
    # was not memory and oomd had nothing to reap — at 22:31:17 the kernel took
    # a general protection fault (non-canonical address) inside the NVIDIA open
    # module while `llama-server` was EXITING:
    #
    #   nvidia_close -> rm_cleanup_file_private -> serverFreeResourceTree
    #     -> memdescDestroy -> osDestroyOsDescriptorPageArray
    #     -> os_unlock_user_pages -> set_page_dirty_lock
    #
    # It died holding NVIDIA's GPU locks, so from 22:35 every task that touched
    # the GPU or waited on an RCU grace period wedged — soft lockups on eleven
    # CPUs, sshd and smbd among them, which is why the box answered TCP
    # handshakes and nothing else. Once, in six boots, no Xid before it (this
    # box also has a documented marginal DRAM line, so a bit flip landing in a
    # page array is not excluded).
    #
    # The default idle unload is 5 minutes, i.e. this exact code path several
    # times a day. Two hours makes it a couple of times a day at most, and it
    # costs nothing that matters: `ai-warden` frees the weights ON DEMAND with a
    # zero `keep_alive` whenever painter needs the room, so "resident longer" is
    # not "resident in the way". A long idle still gives the memory back if the
    # warden is switched off.
    environmentVariables = {
      OLLAMA_MAX_LOADED_MODELS = "1";
      OLLAMA_NUM_PARALLEL = "1";
      OLLAMA_KEEP_ALIVE = "2h";
    } // lib.optionalAttrs qwen38ShimEnabled {
      # The public endpoint remains Ollama's 11434 contract.  The shim starts
      # Ollama on 11436 and lazily routes only sdkyuan's QAT Q2_0 tag to the
      # pinned llama.cpp worker on 11437.  Consequently chatter, book's tunnel,
      # ai-warden and the server controls all keep one endpoint and one unit.
      OLLAMA_SHIM_UPSTREAM = "http://127.0.0.1:11436";
      OLLAMA_SHIM_LLAMA = "http://127.0.0.1:11437";
      OLLAMA_SHIM_OLLAMA_BIN = "${pkgs.ollama-cuda}/bin/ollama";
      OLLAMA_SHIM_LLAMA_BIN = "${qwen38Llama}/bin/llama-server";
      QWEN38_Q2_MODEL = "hf.co/sdkyuan/qwen3.8-27B-qat-q2_0-gguf:latest";
      QWEN38_Q2_MODEL_PATH = "/home/lam/.ollama/models/blobs/sha256-cadd809e691c5fa2cc33a75020930fc404db84528bff9a06177bf77bedc0a877";
      QWEN38_Q2_MODEL_SIZE = "8759266208";
      QWEN38_Q2_CTX = "32768";
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
    # One service and therefore one cgroup for both engines.  The shim is PID 1
    # of the unit and supervises the private Ollama daemon plus the lazy
    # llama-server child.  ai-warden/heavy-gate continue measuring and stopping
    # this exact cgroup, including while the Q2 model is still loading.
    ProtectHome = lib.mkForce "read-only";
    MemoryAccounting = true;
    MemoryHigh = "24G";
    ManagedOOMMemoryPressure = "kill";
    ManagedOOMMemoryPressureLimit = "60%";
  } // lib.optionalAttrs qwen38ShimEnabled {
    ExecStart = lib.mkForce "${pkgs.python3}/bin/python3 ${qwen38Shim}";
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
