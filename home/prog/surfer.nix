{ pkgs, lib, hostProfile, ... }:

# surfer is the live-source QtWebEngine browser. top uses nixpkgs Python/PySide6;
# book/air executes Fedora's system Python/PySide6 because nixpkgs Qt/Mesa cannot
# create an Asahi GPU context. Both wrappers log to ~/.cache/surfer.log, and the
# singleton probe precedes redirection so a link click cannot truncate the
# running browser's log. Python source edits are live; dependency changes need
# a home rebuild. Missing system `adblock` on book degrades to the
# feature-detected domain-only path.
#
let
  # top uses the pinned meatcrowning fork (adblock-rust 0.12.5) because PyPI's
  # final upstream binding is 0.6.0/0.5.6 and lacks procedural actions. The
  # fork is hash-pinned and is owned source; its next engine bump is a manual
  # Rust/API migration. Do not casually move to 0.13.x: `BlockerResult.matched`
  # was removed in 0.13.0. The fork also avoids a build failure if its one-author
  # upstream disappears. The serialized DAT cache is not cross-version
  # compatible; main.py stamps the writer version and rebuilds on mismatch.
  adblock = pkgs.python3Packages.adblock.overridePythonAttrs (old: rec {
    version = "0.7.0";

    src = pkgs.fetchFromGitHub {
      owner = "meatcrowning";
      repo = "python-adblock";
      rev = "f4072c0026e559649b7e571b04cf64b95a620177";
      hash = "sha256-aZQWc7XofSKm5aCZuvTGoQa6aAEwSE7Q1khf/aP/LYY=";
    };

    # The fork is already PEP 621 and has a real version.
    patches = [ ];
    postPatch = "";

    cargoDeps = pkgs.rustPlatform.fetchCargoVendor {
      inherit src version;
      pname = "adblock";
      hash = "sha256-IZkGbSWKuwzzVoJZMdwoKqczGbmr1V+8d7KGAOognI0=";
    };

    # Keep the inherited licence metadata; only provenance changes to our fork.
    meta = old.meta // {
      homepage = "https://github.com/meatcrowning/python-adblock";
      changelog = "https://github.com/meatcrowning/python-adblock/blob/${src.rev}/CHANGELOG.md";
      maintainers = [ ];
    };
  });

  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 adblock ]);

  # top needs Hunspell converted to Chromium's .bdic format. book uses Fedora's
  # QtWebEngine dictionaries and must not build nixpkgs QtWebEngine on Asahi.
  spellDicts = pkgs.runCommand "surfer-spellcheck-dicts" { } ''
    mkdir -p "$out"
    ${pkgs.qt6.qtwebengine}/libexec/qwebengine_convert_dict \
      ${pkgs.hunspellDicts.en_US}/share/hunspell/en_US.dic \
      "$out/en-US.bdic"
  '';

  # Chromium's forced autohinter stripes pixel faces when fontconfig says
  # antialias=false. Pin Botis 4x6 and the web twin antialiased in this wrapper:
  # on-grid sizes remain pixel-exact, while off-grid sizes become soft instead
  # of striped. More Perfect DOS VGA (the non-web face) is intentionally left
  # out because its hinted outlines survive. The explicit last-match pin must
  # win over different host fontconfig order; QtWebEngineProcess inherits it.
  fcConf = pkgs.writeText "surfer-fontconfig.conf" ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <include>/etc/fonts/fonts.conf</include>
      <match target="font">
        <test name="family"><string>Botis 4x6</string></test>
        <edit name="antialias" mode="assign"><bool>true</bool></edit>
      </match>
      <match target="font">
        <test name="family"><string>More Perfect DOS VGA (web)</string></test>
        <edit name="antialias" mode="assign"><bool>true</bool></edit>
      </match>
    </fontconfig>
  '';

  # Refuse sourcing: the wrapper probes the singleton and redirects logs. Use
  # `surfer-qtenv` for a side-effect-free environment instead.
  sourceGuard = ''
    if [ -z "''${BASH_SOURCE[0]-}" ] || [ "''${BASH_SOURCE[0]}" != "$0" ]; then
      echo "surfer: this wrapper must be EXECUTED, not sourced." >&2
      echo "  Sourcing it runs its body: the single-instance probe opens a tab in" >&2
      echo "  the running browser, and the log redirect swallows your shell's stdout." >&2
      echo "  For the Qt environment use:  surfer-qtenv <command> [args...]" >&2
      echo "                          or:  eval \"\$(surfer-qtenv)\"   # in a subshell" >&2
      return 1
    fi
  '';

  # Side-effect-free Qt helper: exec a command, or print exports for
  # `eval "$(surfer-qtenv)"` in a subshell.
  qtenvBody = pkgs.writeShellScript "surfer-qtenv-body" ''
    # `''${!prefix@}` works in nixpkgs' bash without progcomp/compgen.
    if [ "$#" -eq 0 ]; then
      # Include the wrapper's PATH and interpreter; evaluate in a subshell.
      for v in ''${!QT_@} ''${!QML@} ''${!NIXPKGS_QT@} ''${!QTWEBENGINE@} LOCALE_ARCHIVE PATH; do
        if [ -n "''${!v-}" ]; then printf 'export %s=%q\n' "$v" "''${!v}"; fi
      done
      exit 0
    fi
    exec "$@"
  '';

  surfer =
    if hostProfile.isBook then
      # air pulls top's profile before launch and pushes after exit. The sync is
      # timeout-bounded and fail-open, so an unavailable top never blocks launch.
      pkgs.writeShellScriptBin "surfer" ''
        ${sourceGuard}
        # Probe the singleton before profile sync and log truncation; a link click
        # must hand off without disturbing the live instance.
        if /usr/bin/python3 /home/lam/nix/apps/surfer/singleton.py "$@"; then exit 0; fi

        LOG="$HOME/.cache/surfer-sync.log"
        vtbsync() {
          echo "--- $(date -Is) $1" >> "$LOG"
          timeout 90 /usr/bin/python3 /home/lam/nix/apps/surfer/tools/sync.py "$1" \
            >> "$LOG" 2>&1 || echo "  (skipped: rc=$?)" >> "$LOG"
        }
        # Pull happens in main.py after launch; pushing here runs after close and
        # cannot delay the window.
        # Fedora's fontconfig is covered by the same explicit Botis/web pin.
        export FONTCONFIG_FILE="''${FONTCONFIG_FILE:-${fcConf}}"
        # Preserve Qt/Chromium diagnostics and the GPU fallback log.
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
            --set-default FONTCONFIG_FILE ${fcConf} \
            --run ${lib.escapeShellArg sourceGuard} \
            --run 'if ${pyEnv}/bin/python3 /home/lam/nix/apps/surfer/singleton.py "$@"; then exit 0; fi' \
            --run 'exec > "$HOME/.cache/surfer.log" 2>&1' \
            "''${qtWrapperArgs[@]}"

          # Harnesses borrow the same Qt variables and pinned interpreter; use
          # `surfer-qtenv python3 <test>` rather than sourcing the launcher.
          makeWrapper ${qtenvBody} $out/bin/surfer-qtenv \
            --set-default QTWEBENGINE_DICTIONARIES_PATH ${spellDicts} \
            --set-default FONTCONFIG_FILE ${fcConf} \
            --prefix PATH : ${pyEnv}/bin \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ surfer ]
    # air has no nix Qt environment, so its helper is a passthrough.
    ++ lib.optional hostProfile.isBook
      (pkgs.writeShellScriptBin "surfer-qtenv" ''exec ${qtenvBody} "$@"'');

  # MIME/default-browser associations are centralized in mime-defaults.nix;
  # `%U` supplies the start URL and SURFER_DESKTOP_LAUNCH=1 marks human no-URL
  # launches. Declare all browser MIME/scheme types and install the seal icon
  # used by the titlebar.
  home.file.".local/share/icons/hicolor/scalable/apps/surfer.svg".source = ./app-icons/surfer.svg;
  # Mark it as a seal so the panel can tint its currentColor strokes.
  my.appSeals = [ "surfer" ];

  home.file.".local/share/applications/surfer.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=surfer
    GenericName=Web Browser
    Comment=Minimal QtWebEngine browser for the top desktop
    Exec=${pkgs.coreutils}/bin/env SURFER_DESKTOP_LAUNCH=1 ${surfer}/bin/surfer %U
    Icon=surfer
    Terminal=false
    Categories=Network;WebBrowser;
    X-GNOME-UsesNotifications=true
    Keywords=bespoke;
    MimeType=text/html;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;x-scheme-handler/about;
  '';
}
