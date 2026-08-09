{ pkgs, ... }:

{
  # Local LLM serving (RTX 5070). Previously a hand-rolled overlay building
  # ollama from a pinned git src with a manually-recorded vendorHash
  # (flake.nix, commented out) — that broke on a lock update and was never
  # backed up, so nothing here has run in a while. nixpkgs ships its own
  # ollama-cuda derivation now; use that instead of re-deriving one, and take
  # the compositor-cachix approach (sys/base.nix substituters) rather than a
  # local CUDA build.
  # OFF, because `ollama-cuda` does not build at this nixpkgs revision: its
  # vendored llama.cpp fails to configure with "CUDA Toolkit not found"
  # (ggml/src/ggml-cuda/CMakeLists.txt:268) — `nix log
  # /nix/store/55pdhdb436bl3idz4lq5n4zhy37kqgaq-ollama-0.32.1.drv`. Left
  # enable = false rather than reverted, so the next attempt starts from a
  # named failure instead of from the dead overlay again. Turning it on
  # without fixing that breaks every rebuild on `top`.
  services.ollama = {
    enable = false;
    package = pkgs.ollama-cuda;
  };
}
