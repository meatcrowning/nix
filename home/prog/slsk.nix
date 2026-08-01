{ pkgs, lib, host, ... }:

# slsk — the desktop's Soulseek client for the local slskd daemon (source at
# ~/nix/apps/slsk). It replaces the slskd web UI for search + downloads.
#
# Packaging mirrors reader.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon, so exec
#     the SYSTEM python3 with Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env. The app is stdlib-only for its network layer (urllib against the
#     loopback slskd API), so PySide6 is the only runtime dependency.
#
# It runs the LIVE source at ~/nix/apps/slsk/main.py, so QML/Python edits need no
# rebuild — only changing the runtime deps does.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  slsk =
    if host == "air" then
      pkgs.writeShellScriptBin "slsk" ''
        exec /usr/bin/python3 /home/lam/nix/apps/slsk/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "slsk";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/slsk \
            --add-flags /home/lam/nix/apps/slsk/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ slsk ];

  # The desktop entry, so slsk is in the runner. It owns no file type — it is a
  # client over a network service, not an open-a-file app (the same reason
  # painter and goetia declare no MimeType=; see apps/AGENTS.md).
  home.file.".local/share/applications/slsk.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=slsk
    GenericName=Soulseek Client
    Comment=Search and download from Soulseek via the local slskd daemon
    Exec=${slsk}/bin/slsk
    Icon=network-server
    Terminal=false
    Categories=Network;AudioVideo;
    Keywords=bespoke;soulseek;slskd;download;music;
  '';
}
