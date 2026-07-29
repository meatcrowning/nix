{ pkgs, lib, host, ... }:

# surfer — the standalone Qt/QML browser (source at ~/nix/apps/surfer; QtWebEngine,
# i.e. open Chromium, with the browser chrome in the hyprvtb titlebar).
# Packaging mirrors filer.nix exactly, including the air split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon
#     (no Honeykrisp GBM/EGL driver — same root cause as filer/hyprvtb, see
#     docs/agents/air-port-nextsteps.md), so exec the SYSTEM python3 with Fedora's dnf-installed
#     python3-pyside6 (which ships QtWebEngine and runs on Asahi's Mesa).
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the
#     Qt env so QtWebEngine finds its resources.
#
# BOTH wrappers send the app's stdio to ~/.cache/surfer.log, truncated once per
# launch. Launched from a runner or a link click, surfer's stdout/stderr are
# /dev/null otherwise — which silently discarded every `surfer adblock:` line
# and the mid-session GPU/raster fallback alongside ~/.cache/surfer-gpu.log.
# The single-instance probe must run BEFORE the redirect on either host (see
# the air branch's comment): a link click that hands the URL to the running
# browser must not truncate that session's log out from under its open fd.
#
# Both run the LIVE source at ~/nix/apps/surfer/main.py — day-to-day edits need no
# rebuild on either machine. (Adding a Python dep like `adblock` below is the
# exception: it needs one `rbhome` to land in pyEnv. On air the ad blocker
# looks for `adblock` in the system python — `pip install --user adblock` to
# get the full engine there; without it, it falls back to domain-only blocking.
# Note that PyPI only has 0.6.0, so air gets network + plain cosmetic filtering
# but NOT procedural filtering — the engine code feature-detects, so this is a
# degradation and not a break. See the `adblock` override below for why.)
#
let
  # `adblock` — Brave's adblock-rust engine (the uBlock-Origin-class filter
  # engine); surfer uses it for full network + cosmetic filtering.
  #
  # WHY THIS IS NOT `ps.adblock`. nixpkgs ships python-adblock 0.6.0, which is
  # upstream's LAST release: ArniDagur/python-adblock has been dead since
  # 2023-03 and pins the Rust crate at `=0.5.6`. **Procedural cosmetic
  # filtering — `:has()`, `:has-text()`, `:upward()`, `:remove()`, a large and
  # growing share of every modern uBO list — landed in adblock-rust 0.9.0**, so
  # on 0.6.0 the binding has no `procedural_actions` field at all and every one
  # of those rules is parsed and then silently discarded. There is no newer
  # release, on PyPI or anywhere: this is the only way to that field.
  #
  # jampe/python-adblock rebases the same pyo3 binding onto adblock-rust 0.12.5
  # and exposes `procedural_actions`, `add_resources` and
  # `hidden_class_id_selectors`. Pinned to an exact rev by hash and treated as
  # SOURCE WE OWN, not a dependency we track — upstream is a one-author fork of
  # a dead project, created 2026-07-20, not published to PyPI, and it will not
  # be maintained for us. The standing cost is that this flake now carries a
  # vendored Rust crate whose next adblock-rust bump is ours to do by hand.
  #
  # `owner` is meatcrowning/python-adblock, OUR FORK of jampe's tree at the same
  # rev, and that is the point: the hash already freezes the CONTENT, so nothing
  # can move under a rebuild, but a hash cannot fetch a repo that has been
  # deleted. A 0-star one-author upstream can vanish, and then no machine
  # without the store path already warm — book, or this one after a `nix-collect-
  # garbage` — can build surfer at all. Forking costs one line and removes that
  # single point of failure entirely. Re-point at upstream only to pick up a new
  # rev, and fork that too.
  #
  # Staying at the fork's 0.12.5 rather than adblock-rust's latest (0.13.2) is
  # deliberate: 0.13.0 removed `BlockerResult.matched` in favour of
  # `should_block()`, which this binding's `lib.rs` and its type stubs both
  # still use — bumping means editing the fork's Rust, for no filtering we do
  # not already get.
  #
  # **The serialized cache is NOT compatible across this bump.** adblock-rust's
  # DAT format has offered no cross-version compatibility since 0.10.0, so a
  # `~/.cache/surfer/filters/engine.dat` written by 0.5.6 is garbage to 0.12.5.
  # The engine code in apps/surfer/main.py must stamp the cache with the
  # `adblock.__version__` that wrote it and rebuild on any mismatch — a one-off
  # manual delete is not enough, since the next bump has the same problem.
  adblock = pkgs.python3Packages.adblock.overridePythonAttrs (old: rec {
    version = "0.7.0";

    src = pkgs.fetchFromGitHub {
      owner = "meatcrowning";
      repo = "python-adblock";
      rev = "f4072c0026e559649b7e571b04cf64b95a620177";
      hash = "sha256-aZQWc7XofSKm5aCZuvTGoQa6aAEwSE7Q1khf/aP/LYY=";
    };

    # The fork is already PEP 621 and carries a real version, so nixpkgs'
    # backport patch and its "0.0.0" substitution are both dead here.
    patches = [ ];
    postPatch = "";

    cargoDeps = pkgs.rustPlatform.fetchCargoVendor {
      inherit src version;
      pname = "adblock";
      hash = "sha256-IZkGbSWKuwzzVoJZMdwoKqczGbmr1V+8d7KGAOognI0=";
    };

    # Inherited meta still pointed at the abandoned upstream. Licence is
    # unchanged (the binding is MIT OR Apache-2.0, both LICENSE files present in
    # the fork; adblock-rust underneath it has been MPL-2.0 all along, at 0.5.6
    # as much as at 0.12.5) — only the provenance moves.
    meta = old.meta // {
      homepage = "https://github.com/meatcrowning/python-adblock";
      changelog = "https://github.com/meatcrowning/python-adblock/blob/${src.rev}/CHANGELOG.md";
      maintainers = [ ];
    };
  });

  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 adblock ]);

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
      # ~/nix/apps/surfer/tools/sync.py): merge top's cookies + userscripts in
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
        # Single instance FIRST, before anything else in this wrapper runs.
        # surfer is the default browser now (home/prog/mime-defaults.nix), so a
        # link clicked in another app lands here; apps/surfer/singleton.py hands
        # the URL to the running instance over its socket and exits 0, and only
        # exits 10 (falling through to a real launch) when nobody is listening.
        # It has to happen before the sync bracket and before the log
        # truncation below: those would otherwise refuse twice per click and
        # truncate the LIVE session's log out from under its open fd.
        if /usr/bin/python3 /home/lam/nix/apps/surfer/singleton.py "$@"; then exit 0; fi

        LOG="$HOME/.cache/surfer-sync.log"
        vtbsync() {
          echo "--- $(date -Is) $1" >> "$LOG"
          timeout 90 /usr/bin/python3 /home/lam/nix/apps/surfer/tools/sync.py "$1" \
            >> "$LOG" 2>&1 || echo "  (skipped: rc=$?)" >> "$LOG"
        }
        [ -n "''${SURFER_NO_SYNC:-}" ] || vtbsync pull
        # Launched from the runner, so the app's own stdio has nowhere to go and
        # Qt/Chromium diagnostics were being thrown away. Keep one session's
        # worth (truncated per launch) — this is how the mid-session GPU/raster
        # fallback gets caught alongside ~/.cache/surfer-gpu.log.
        /usr/bin/python3 /home/lam/nix/apps/surfer/main.py "$@" \
          > "$HOME/.cache/surfer.log" 2>&1
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
            --add-flags /home/lam/nix/apps/surfer/main.py \
            --set-default QTWEBENGINE_DICTIONARIES_PATH ${spellDicts} \
            --run 'if ${pyEnv}/bin/python3 /home/lam/nix/apps/surfer/singleton.py "$@"; then exit 0; fi' \
            --run 'exec > "$HOME/.cache/surfer.log" 2>&1' \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ surfer ];

  # Desktop entry so surfer shows up in the runner and is eligible for http(s).
  # It IS now the default browser — that association, plus Plasma's separate
  # kdeglobals BrowserApplication key and $BROWSER, is set centrally in
  # home/prog/mime-defaults.nix. `%U` is load-bearing for that: main.py takes
  # the first non-flag argv as the start URL.
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
