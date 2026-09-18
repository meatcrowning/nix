{ lib, cudaPackages, cmake, ninja, pkg-config, openssl, fetchFromGitHub,
  autoAddDriverRunpath }:

# Separate from stock llama.cpp: PQ2_0 needs Prism's Hadamard kernels.
cudaPackages.backendStdenv.mkDerivation {
  pname = "bonsai-llama";
  version = "2026-09-17-f0a2b5d";
  src = fetchFromGitHub {
    owner = "PrismML-Eng";
    repo = "llama.cpp";
    rev = "f0a2b5dc9ea066780b9b410d2c0f95d675859bf7";
    sha256 = "0wda8ad3r5czhz09kx97qf5a9idm0l0kqp546dlpffziy6yv1hg3";
  };
  nativeBuildInputs = [ cmake ninja pkg-config cudaPackages.cuda_nvcc autoAddDriverRunpath ];
  buildInputs = [ openssl cudaPackages.cccl cudaPackages.cuda_cudart cudaPackages.libcublas ];
  cmakeFlags = [
    "-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON"
    "-DCMAKE_INSTALL_RPATH=${placeholder "out"}/lib"
    "-DCMAKE_INSTALL_RPATH_USE_LINK_PATH=ON"
    "-DGGML_NATIVE=OFF" "-DGGML_CUDA=ON"
    "-DCMAKE_CUDA_ARCHITECTURES=120" "-DGGML_CPU_ALL_VARIANTS=OFF"
    "-DLLAMA_BUILD_TESTS=OFF" "-DLLAMA_BUILD_EXAMPLES=OFF"
    "-DLLAMA_BUILD_APP=OFF" "-DLLAMA_BUILD_UI=OFF"
    "-DLLAMA_BUILD_SERVER=ON" "-DLLAMA_BUILD_COMMIT=f0a2b5d"
  ];
  # CUDA template compilation is RAM-heavy; avoid the host's full job count.
  ninjaFlags = [ "-j4" "llama-server" ];
  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin $out/lib
    cp bin/llama-server $out/bin/
    cp -a bin/*.so* $out/lib/
    runHook postInstall
  '';
  meta = {
    description = "Pinned Prism llama-server for Bonsai ternary weights on top";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
  };
}
