{
  pkgs,
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
  };
}
