# Backport nixpkgs 7990e968cb8d (2026-07-25; our pin is 2026-07-18, so it
# is not in the tree): setup-cuda-hook's setupCUDAToolkit_ROOT builds
# CUDAToolkit_ROOT from the marked redist paths (cudart, libcublas, cccl)
# but never adds nvcc's dir, so any child cmake build that inherits the env
# var and does find_package(CUDAToolkit) fails with "CUDA Toolkit not
# found" at ggml-cuda/CMakeLists.txt:268 — which is exactly the ollama-cuda
# failure (llama.cpp is a cmake ExternalProject child). Upstream appends the
# nvcc dir to CUDAToolkit_ROOT in the hook itself; mirroring it at the
# ollama level keeps the blast radius to this one package. Drop the overlay
# when the nixpkgs input rolls past 2026-07-25 (the hook fix arrives in the
# same bump).
final: prev: {
  ollama-cuda = prev.ollama-cuda.overrideAttrs (old: {
    preBuild = ''
      local nvccExe
      if nvccExe="$(type -P nvcc)"; then
        export CUDAToolkit_ROOT="''${nvccExe%/bin/nvcc}''${CUDAToolkit_ROOT:+;$CUDAToolkit_ROOT}"
      fi
    '' + (old.preBuild or "");
  });
}
