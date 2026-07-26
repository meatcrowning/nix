{ pkgs, lib, host, ... }:

# surfer — the standalone Qt/QML browser (source at ~/nix/surfer; QtWebEngine,
# i.e. open Chromium, with the browser chrome in the hyprvtb titlebar).
# Packaging mirrors filer.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon
#     (no Honeykrisp GBM/EGL driver — same root cause as filer/hyprvtb, see
#     docs/air-port-nextsteps.md), so exec the SYSTEM python3 with Fedora's dnf-installed
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
      # air additionally brackets the run with the profile handoff (see
      # ~/nix/surfer/tools/sync.py): merge top's cookies + userscripts in
      # before the window opens, merge ours back out after it closes.
      #
      # Only air does this, and that is not an oversight: Fedora runs no
      # sshd, so top cannot reach book — book is the only machine that can
      # initiate. It still converges both ways, because book pulls top's
      # latest at ITS launch and pushes its own at ITS exit.
      #
      # Never allowed to get between the user and the browser: the sync is
      # timeout-bounded and `|| true`, so top being asleep, off the network
      # or mid-session just logs and launches anyway. Chatter goes to
      # ~/.cache/surfer-sync.log, not the terminal.
      pkgs.writeShellScriptBin "surfer" ''
        LOG="$HOME/.cache/surfer-sync.log"
        vtbsync() {
          echo "--- $(date -Is) $1" >> "$LOG"
          timeout 90 /usr/bin/python3 /home/lam/nix/surfer/tools/sync.py "$1" \
            >> "$LOG" 2>&1 || echo "  (skipped: rc=$?)" >> "$LOG"
        }
        [ -n "''${SURFER_NO_SYNC:-}" ] || vtbsync pull
        /usr/bin/python3 /home/lam/nix/surfer/main.py "$@"
        rc=$?
        [ -n "''${SURFER_NO_SYNC:-}" ] || vtbsync push
        exit $rc
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
    Keywords=bespoke;
    MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;
  '';
}
