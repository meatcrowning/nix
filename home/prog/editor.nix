{ pkgs, lib, host, ... }:

# editor — the desktop's text editor, with Kate's core editing (source at
# ~/nix/apps/editor). Packaging mirrors reader.nix exactly, including the air
# split:
#
#   * air: nixpkgs' Qt/Mesa can't create a GPU context on Apple Silicon (no
#     Honeykrisp GBM/EGL driver — same root cause as filer/viewer/reader, see
#     docs/agents/air-port-nextsteps.md), so exec the SYSTEM python3 with
#     Fedora's python3-pyside6.
#   * top: a plain wrapper over nixpkgs' python3 + PySide6, wrapped with the Qt
#     env.
#
# **Nothing here is architecture-specific.** editor draws only text and imports
# only PySide6 + the stdlib — the same set reader already needs on both machines
# — so book gets it from the shared `home/` tree, and the aarch64 gates the
# other apps need (`pkgs.stdenv.hostPlatform.isx86_64`) do not apply.
#
# The ONE runtime dependency beyond that is the spell checker's dictionary, and
# it is deliberately not a Python module: `pylib/spellcheck.py` talks to the
# `hunspell` BINARY in pipe mode, so `SPELL_HUNSPELL`/`SPELL_DICPATH` below are
# the whole wiring on top. **book gets nothing here** — its branch execs
# Fedora's python3 with no wrapper, so the checker resolves `hunspell` from
# `$PATH` and the dictionary from `/usr/share/hunspell`, i.e. it works if
# `hunspell` + `hunspell-en-US` are dnf-installed and marks NOTHING if they are
# not (docs/DESIGN.md §10 — an input with no dictionary behaves exactly as it did
# before). Nothing is x86-only about either package; keeping book on the system
# copy is what avoids a second nixpkgs Qt/Mesa closure on the laptop.
#
# Both run the LIVE source at ~/nix/apps/editor/main.py, so QML/Python edits need
# no rebuild — only changing the runtime deps or this file does.
let
  pyEnv = pkgs.python3.withPackages (ps: [ ps.pyside6 ]);

  editor =
    if host == "air" then
      pkgs.writeShellScriptBin "editor" ''
        exec /usr/bin/python3 /home/lam/nix/apps/editor/main.py "$@"
      ''
    else
      pkgs.stdenv.mkDerivation {
        pname = "editor";
        version = "live";
        dontUnpack = true;

        nativeBuildInputs = [ pkgs.qt6.wrapQtAppsHook pkgs.makeWrapper ];
        buildInputs = [ pyEnv pkgs.qt6.qtdeclarative ];

        dontWrapQtApps = true; # we wrap the python launcher ourselves
        installPhase = ''
          runHook preInstall
          mkdir -p $out/bin
          makeWrapper ${pyEnv}/bin/python3 $out/bin/editor \
            --add-flags /home/lam/nix/apps/editor/main.py \
            --set-default SPELL_HUNSPELL ${pkgs.hunspell}/bin/hunspell \
            --set-default SPELL_DICPATH ${pkgs.hunspellDicts.en_US}/share/hunspell \
            "''${qtWrapperArgs[@]}"
          runHook postInstall
        '';
      };
in
{
  home.packages = [ editor ];

  # Desktop entry, so editor is in the runner and is ELIGIBLE for the text types
  # it can actually edit. Being the DEFAULT for any of them is set centrally, in
  # home/prog/mime-defaults.nix — and this app is deliberately NOT in that list
  # yet: `text/markdown` already belongs to reader and `text/html` to surfer, and
  # quietly taking either would change what double-clicking a file does without
  # him asking for it. `xdg-mime default editor.desktop text/x-python` (or a line
  # in mime-defaults.nix) is the one-line change if he wants it.
  #
  # `%F` and not `%f`: editor is genuinely multi-document — several files open as
  # several tabs in one window — and `main.py` honours every path it is handed
  # (apps/AGENTS.md: an app may only claim a field code it can honour). It also
  # accepts `+N` to open at a line, which is what a compiler error or `git grep`
  # hands you.
  home.file.".local/share/applications/editor.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=editor
    GenericName=Text Editor
    Comment=Edit text and source files
    Exec=${editor}/bin/editor %F
    Icon=text-x-generic
    Terminal=false
    Categories=Development;TextEditor;Utility;
    Keywords=bespoke;text;code;source;edit;
    MimeType=text/plain;text/x-python;text/x-nix;text/x-lua;text/x-c;text/x-c++src;text/x-c++hdr;text/x-chdr;text/x-csrc;text/x-shellscript;application/json;application/x-shellscript;text/x-qml;text/x-diff;text/x-patch;text/csv;application/xml;text/xml;
  '';
}
