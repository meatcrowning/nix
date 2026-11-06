{ pkgs, lib, hostProfile, ... }:

# CUDA and the controller stay on top; book runs only the native SSH client.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);
  trainer = if !hostProfile.isTop then pkgs.writeShellScriptBin "moss-trainer" ''
    export TRAINER_SSH_HOST=top
    export PATH=${lib.makeBinPath [ pkgs.rsync ]}:$PATH
    exec /usr/bin/python3 /home/lam/nix/apps/trainer/main.py "$@"
  '' else pkgs.stdenv.mkDerivation {
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
        --prefix PATH : ${lib.makeBinPath [ pkgs.git pkgs.uv pkgs.patchelf pkgs.rsync pkgs.systemd ]} \
        --prefix LD_LIBRARY_PATH : /run/opengl-driver/lib:${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib pkgs.glib pkgs.libGL ]} \
        "''${qtWrapperArgs[@]}"
    '';
  };
in {
  systemd.user.services.moss-trainer-controller = lib.mkIf hostProfile.isTop {
    Unit.Description = "Persistent MOSS training controller";
    Service = {
      ExecStart = "${trainer}/bin/moss-trainer --controller";
      UMask = "0077";
      KillMode = "process";
      # On an unexpected controller exit, stdin EOF lets the worker save and
      # stop. Do not SIGKILL it midway through publishing a checkpoint.
    };
  };
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
