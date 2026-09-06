{ pkgs, lib, host, ... }:

# The desktop's default handlers, shared by `top` and `book`. App `.desktop`
# files make handlers eligible; this module makes the named types default.
# `mime-files/set-defaults.py` edits only those keys in place, preserving the
# user's other associations and remaining idempotent across activation.
#
# This intentionally replaces the previous defaults on `top`. The old entries
# remain in `[Added Associations]`, so they are still available through
# "Open with"; change the tables below to revert.
let
  filerTypes = [ "inode/directory" ];

  # Mirrors viewer's IMAGE_EXTS / VIDEO_EXTS (apps/viewer/main.py) — viewer
  # really does play video, through QtMultimedia's ffmpeg backend, so
  # registering it for video/* is not a promise it can't keep. Types with no
  # matching extension in that set are deliberately absent.
  viewerTypes = [
    "image/png" "image/jpeg" "image/gif" "image/webp" "image/bmp"
    "image/svg+xml" "image/avif" "image/jxl" "image/tiff" "image/x-icon"
    "image/vnd.microsoft.icon" "image/x-portable-pixmap"
    "image/x-portable-graymap"
    "video/mp4" "video/x-matroska" "video/webm" "video/quicktime"
    "video/x-msvideo" "video/mpeg" "video/x-ms-wmv" "video/x-flv"
    "video/mp2t" "video/ogg" "video/3gpp"
  ];

  # Audio handled by `player`, derived from `apps/player/main.py`'s
  # `AUDIO_EXTS` through shared-mime-info globs. Direct file opens are supported
  # by `paths_from_argv`/`Player.playPaths` and the queue `OPEN` verb (covered by
  # `apps/player/tools/open-path-test.py`), including files outside the library.
  # WAV aliases are listed explicitly because detectors may return either alias;
  # video Ogg types remain with `viewer`.
  playerTypes = [
    "audio/flac" "audio/mpeg" "audio/mp4" "audio/x-m4a" "audio/ogg"
    "audio/opus" "audio/x-dsf" "audio/x-wavpack" "audio/x-ape"
    "audio/x-aiff" "audio/vnd.wave" "audio/x-wav" "audio/wav"
    "audio/x-musepack" "audio/x-tta" "audio/x-dff"
    "audio/x-vorbis+ogg" "audio/x-opus+ogg" "audio/x-flac+ogg"
    "audio/x-speex+ogg"
  ];

  # `painter` and `board` get no association: painter has no file-open path, and
  # board edits `~/nix/docs/board.<hostname>.md` rather than viewing markdown.

  surferTypes = [
    "text/html" "application/xhtml+xml"
    "x-scheme-handler/http" "x-scheme-handler/https" "x-scheme-handler/about"
  ];

  # Markdown and PDF, to `reader`. Filer's non-image `xdg-open` path consults
  # this table; plain text remains with the user's editor because reader is not
  # a text editor. PDF support is implemented by `apps/reader/pdfdoc.py`.
  readerTypes = [ "text/markdown" "text/x-markdown" "application/pdf" ];

  # Plain text and source code, matching `editor.nix`'s `MimeType=` line.
  # Markdown and HTML stay with reader and surfer respectively.
  editorTypes = [
    "text/plain" "text/x-python" "text/x-nix" "text/x-lua" "text/x-c"
    "text/x-c++src" "text/x-c++hdr" "text/x-chdr" "text/x-csrc"
    "text/x-shellscript" "application/json" "application/x-shellscript"
    "text/x-qml" "text/x-diff" "text/x-patch" "text/csv" "application/xml"
    "text/xml"
  ];

  assoc =
    (map (t: "${t}=filer.desktop") filerTypes)
    ++ (map (t: "${t}=viewer.desktop") viewerTypes)
    ++ (map (t: "${t}=player.desktop") playerTypes)
    ++ (map (t: "${t}=surfer.desktop") surferTypes)
    ++ (map (t: "${t}=reader.desktop") readerTypes)
    ++ (map (t: "${t}=editor.desktop") editorTypes);

  # Plasma gets a separate `kde-mimeapps.list`, selected by XDG's
  # `$desktop-mimeapps.list` precedence. Hyprland never reads it, and Plasma
  # never reads the generic table. Only the types claimed by the vendored apps
  # are overridden: video uses Haruna, source/markdown uses Kate, PDF uses
  # Okular, and links use the host's installed Vivaldi desktop entry.
  vivaldiDesktop =
    if host == "air" then "com.vivaldi.Vivaldi.desktop" else "vivaldi-stable.desktop";

  kdeAssoc =
    (map (t: "${t}=org.kde.dolphin.desktop") filerTypes)
    ++ (map (t: "${t}=${if lib.hasPrefix "video/" t
                        then "org.kde.haruna.desktop"
                        else "org.kde.gwenview.desktop"}") viewerTypes)
    ++ (map (t: "${t}=org.kde.elisa.desktop") playerTypes)
    ++ (map (t: "${t}=${vivaldiDesktop}") surferTypes)
    ++ (map (t: "${t}=${if t == "application/pdf"
                        then "org.kde.okular.desktop"
                        else "org.kde.kate.desktop"}") readerTypes)
    ++ (map (t: "${t}=org.kde.kate.desktop") editorTypes);

  setDefaults = "${pkgs.python3}/bin/python3 ${./mime-files/set-defaults.py}";

  # Plasma's in-app browser comes from `kdeglobals` rather than the scheme
  # handler, and that file has no per-session variant. The same idempotent
  # helper runs from Hyprland autostart or Plasma's autostart entry, choosing
  # Vivaldi for KDE and surfer otherwise.
  sessionDefaults = pkgs.writeShellScriptBin "desktop-session-defaults" ''
    set -u
    case ":$(printf '%s' "''${XDG_CURRENT_DESKTOP:-}" | tr '[:lower:]' '[:upper:]'):" in
      *:KDE:*) browser=${vivaldiDesktop} ;;
      *)       browser=surfer.desktop ;;
    esac
    exec ${setDefaults} --file kdeglobals --section General --only-if-exists \
      "BrowserApplication=$browser"
  '';
in
{
  # Defaults are consulted only after type detection. Hyprland's generic
  # `xdg-open` path falls back to `file`, which reads content but not globs; on
  # `book` that misclassified `.md`, `.svg`, and `.csv` despite shared-mime-info.
  # `FileMimeInfo` supplies the glob-aware `mimetype` detector. It is on the
  # shell profile for `top`; `filer.nix` and `reader.nix` also put it in the
  # wrapper PATH so graphical `xdg-open` calls get the same result on both
  # hosts.
  home.packages = [ pkgs.perlPackages.FileMimeInfo sessionDefaults ];

  # Plasma's autostart counterpart to the `hl.exec_cmd` in Hyprland's
  # `hyprland.lua`; each session reads only its own startup mechanism.
  xdg.configFile."autostart/desktop-session-defaults.desktop".text = ''
    [Desktop Entry]
    Type=Application
    Name=Desktop session defaults
    Comment=Point KDE's BrowserApplication at this session's browser
    Exec=${sessionDefaults}/bin/desktop-session-defaults
    NoDisplay=true
    X-GNOME-Autostart-enabled=true
  '';

  home.activation.desktopDefaults =
    lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      run ${setDefaults} ${lib.escapeShellArgs assoc}

      # Keep Plasma's answers in a separate file; XDG reads it only in KDE.
      run ${setDefaults} --file kde-mimeapps.list ${lib.escapeShellArgs kdeAssoc}

      # BrowserApplication is per-session, so the startup helper owns it;
      # activation only refreshes the current session after a switch.
      run ${sessionDefaults}/bin/desktop-session-defaults || true

      # Refresh the cache used by "Open with…" for the local app entries.
      run ${pkgs.desktop-file-utils}/bin/update-desktop-database \
        "''${XDG_DATA_HOME:-$HOME/.local/share}/applications" || true
    '';

  # For anything that consults $BROWSER rather than the MIME database (git,
  # some CLI tools). Lands in hm-session-vars.sh, so it applies to shells and
  # sessions started after the next login.
  home.sessionVariables.BROWSER = "surfer";
}
