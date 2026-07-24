{ pkgs, lib, host, ... }:

# surfer — the standalone Qt/QML browser (source at ~/nix/surfer; QtWebEngine,
# i.e. open Chromium, with the browser chrome in the hyprvtb titlebar).
# Packaging mirrors filer.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon
#     (no Honeykrisp GBM/EGL driver — same root cause as filer/hyprvtb, see
#     NEXTSTEPS.md), so exec the SYSTEM python3 with Fedora's dnf-installed
#     python3-pyside6 (which ships QtWebEngine and runs on Asahi's Mesa).
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the
#     Qt env so QtWebEngine finds its resources.
#
# Both run the LIVE source at ~/nix/surfer/main.py — day-to-day edits need no
# rebuild on either machine. (Adding a Python dep like `adblock` below is the
# exception: it needs one `rbhome` to land in pyEnv. On air the ad blocker
# looks for `adblock` in the system python — `pip install --user adblock` to
# get the full engine there; without it, it falls back to domain-only blocking.)
#
# `adblock` is Brave's adblock-rust engine (the uBlock-Origin-class filter
# engine) — surfer uses it for full network + cosmetic filtering.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ps.adblock ]);

  # Spell-check dictionaries for QtWebEngine. Chromium doesn't read Hunspell
  # .dic/.aff directly — it wants them compiled to its own .bdic format, which
  # qwebengine_convert_dict (shipped inside qtwebengine) produces. The top
  # wrapper points QTWEBENGINE_DICTIONARIES_PATH here; Main.qml's profile sets
  # spellCheckEnabled + spellCheckLanguages ["en-US"]. The file MUST be named by
  # the exact BCP-47 tag Chromium looks up (en-US.bdic), NOT the Hunspell locale
  # (en_US). Without this dir the engine simply reports no suggestions.
  spellDicts = pkgs.runCommand "surfer-spellcheck-dicts" { } ''
    mkdir -p "$out"
    ${pkgs.qt6.qtwebengine}/libexec/qwebengine_convert_dict \
      ${pkgs.hunspellDicts.en_US}/share/hunspell/en_US.dic \
      "$out/en-US.bdic"
  '';

  surfer =
    if host == "air" then
      pkgs.writeShellScriptBin "surfer" ''
        exec /usr/bin/python3 /home/lam/nix/surfer/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "surfer";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative pkgs.qt6.qtwebengine ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/surfer \
            --add-flags /home/lam/nix/surfer/main.py \
            --set-default QTWEBENGINE_DICTIONARIES_PATH ${spellDicts} \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ surfer ];

  # Desktop entry so surfer shows up in the runner. Not registered as the
  # default browser (x-scheme-handler/http) yet — it's a prototype; flip that
  # on deliberately once it's earned it.
  home.file.".local/share/applications/surfer.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=surfer
    GenericName=Web Browser
    Comment=Minimal QtWebEngine browser for the top desktop
    Exec=${surfer}/bin/surfer %U
    Icon=web-browser
    Terminal=false
    Categories=Network;WebBrowser;
    MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;
  '';
}
