{ lib, cudaPackages, cmake, ninja, pkg-config, openssl, fetchFromGitHub,
  autoAddDriverRunpath }:

# Mainline llama.cpp 29b52d39 (inkling2_loop arch and chat parser, #32694) plus
# #32704, which re-shares the loop slots after the NVFP4 scale pass.  Without it
# Unsloth's Mainline_Support quants lose their expert scales on passes 2-3
# (perplexity ~130 instead of 7.65).  Drop the fork once #32704 is merged.
cudaPackages.backendStdenv.mkDerivation {
  pname = "inkling-llama";
  version = "2026-11-20-2a28df0";
  src = fetchFromGitHub {
    owner = "danielhanchen";
    repo = "llama.cpp";
    rev = "2a28df0f9bd55c4975b6bffb35229a6020720f13";
    sha256 = "07kpynwl352a6n8vdar5yda8va4x5dhvnv5gaibb6zdg07x6v02n";
  };
  nativeBuildInputs = [ cmake ninja pkg-config cudaPackages.cuda_nvcc autoAddDriverRunpath ];
  buildInputs = [ openssl cudaPackages.cccl cudaPackages.cuda_cudart cudaPackages.libcublas
                 cudaPackages.cuda_nvml_dev ];
  cmakeFlags = [
    "-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON"
    "-DCMAKE_INSTALL_RPATH=${placeholder "out"}/lib"
    "-DCMAKE_INSTALL_RPATH_USE_LINK_PATH=ON"
    "-DGGML_NATIVE=OFF" "-DGGML_CUDA=ON"
    "-DCMAKE_CUDA_ARCHITECTURES=120" "-DGGML_CPU_ALL_VARIANTS=OFF"
    # Most expert weights run on the CPU (see the shim's Inkling route), so
    # build for top's Zen 5 explicitly rather than the portable AVX2 floor.
    "-DGGML_AVX=ON" "-DGGML_AVX2=ON" "-DGGML_FMA=ON" "-DGGML_F16C=ON"
    "-DGGML_BMI2=ON" "-DGGML_AVX512=ON" "-DGGML_AVX512_VBMI=ON" "-DGGML_AVX512_VNNI=ON"
    "-DGGML_AVX512_BF16=ON" "-DGGML_AVX_VNNI=ON"
    "-DLLAMA_BUILD_TESTS=OFF" "-DLLAMA_BUILD_EXAMPLES=OFF"
    "-DLLAMA_BUILD_APP=OFF" "-DLLAMA_BUILD_UI=OFF"
    "-DLLAMA_BUILD_SERVER=ON" "-DLLAMA_BUILD_COMMIT=2a28df0"
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
    description = "llama-server with Inkling 2 Mini loop support for top";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
  };
}
