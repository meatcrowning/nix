{ pkgs, lib, host, ... }:

# reader — the desktop's markdown reader (source at ~/nix/apps/reader).
# Packaging mirrors viewer.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon (no
#     Honeykrisp GBM/EGL driver — same root cause as filer/viewer/hyprvtb, see
#     docs/agents/air-port-nextsteps.md), so exec the SYSTEM python3 with
#     Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env. reader draws only text — no image or media plugins are needed, which
#     is why this buildInputs list is shorter than viewer's.
#
# Both run the LIVE source at ~/nix/apps/reader/main.py, so QML/Python edits need
# no rebuild — only changing the runtime deps does.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  reader =
    if host == "air" then
      pkgs.writeShellScriptBin "reader" ''
        exec /usr/bin/python3 /home/lam/nix/apps/reader/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "reader";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/reader \
            --add-flags /home/lam/nix/apps/reader/main.py \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ reader ];

  # Desktop entry, so reader is in the runner and is eligible for markdown.
  # Being the DEFAULT for text/markdown is set centrally, in
  # home/prog/mime-defaults.nix — a MimeType= line only makes an app eligible.
  # That is also the whole of filer's integration: filer opens a non-image with
  # `xdg-open`, which consults the MIME database, so a `.md` lands here with no
  # change to filer at all.
  #
  # `%f` and not `%F`: reader shows ONE document per window (its split view is
  # two documents chosen by the user, not a queue), so several files means
  # several windows — which is what a single-file field code asks the launcher
  # for. It also accepts a DIRECTORY, opening that directory's README.
  home.file.".local/share/applications/reader.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=reader
    GenericName=Markdown Reader
    Comment=Browse and read markdown documents
    Exec=${reader}/bin/reader %f
    Icon=text-x-generic
    Terminal=false
    Categories=Office;Viewer;TextEditor;
    Keywords=bespoke;markdown;md;
    MimeType=text/markdown;text/x-markdown;
  '';
}
