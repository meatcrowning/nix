{ pkgs, lib, hostProfile, ... }:

# Local CUDA training is top-only. Book has no CUDA device; its existing
# apps remain unchanged. The ML environment is isolated from Painter/ComfyUI.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);
  trainer = pkgs.stdenv.mkDerivation {
    pname = "moss-trainer";
    version = "live";
    dontUnpack = true;
    nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
    buildInputs = [ pyEnv pkgs.kdePackages.plasma-integration pkgs.kdePackages.oxygen ];
    dontWrapQtApps = true;
    installPhase = ''
      mkdir -p $out/bin
      makeWrapper ${pyEnv}/bin/python3 $out/bin/moss-trainer \
        --add-flags /home/lam/nix/apps/trainer/main.py \
        --set TRAINER_BASE_PYTHON ${pkgs.python312}/bin/python3 \
        --set TRAINER_DYNAMIC_LINKER ${pkgs.stdenv.cc.bintools.dynamicLinker} \
        --set TRITON_LIBCUDA_PATH /run/opengl-driver/lib \
        --set PYTHONNOUSERSITE 1 \
        --prefix PATH : ${lib.makeBinPath [ pkgs.git pkgs.uv pkgs.patchelf ]} \
        --prefix LD_LIBRARY_PATH : /run/opengl-driver/lib:${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib pkgs.glib pkgs.libGL ]} \
        "''${qtWrapperArgs[@]}"
    '';
  };
in lib.mkIf hostProfile.isTop {
  home.packages = [ trainer ];
  home.file.".local/share/applications/moss-trainer.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=MOSS Trainer
    GenericName=LoRA Trainer
    Comment=Train MOSS-Image style and character LoRAs
    Exec=${trainer}/bin/moss-trainer
    Icon=applications-science
    Terminal=false
    Categories=Graphics;
    Keywords=bespoke;moss;lora;training;
  '';
}
