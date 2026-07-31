{ pkgs, lib, ... }:

# The desktop's default handlers — one place, both machines.
#
# The user's request: "the default file manager should be filer, the default
# image and video viewer should be viewer, and the default browser should be
# surfer". Each app already ships a `.desktop` entry from its own
# `home/prog/<app>.nix` (that's where MimeType= and Exec= live, because the
# Exec path is the app's own store path). What was missing was the *default*
# association — a MimeType= line only makes an app eligible, it never makes it
# chosen.
#
# NOT `xdg.mimeApps`: that option wants to own ~/.config/mimeapps.list
# outright, and a real one already exists on both machines holding the user's
# own associations plus an [Added Associations] section home-manager would not
# reproduce. It would refuse with a clobber error, or with force, discard them.
#
# NOT `xdg-mime default` (what filer.nix used to do): its behaviour forks on the
# detected desktop environment, and activation runs with no XDG_CURRENT_DESKTOP,
# so what it actually writes depends on the machine. `mime-files/set-defaults.py`
# does one deterministic in-place edit of the named keys and leaves every other
# line of the file verbatim; it is idempotent, so it re-runs cleanly on every
# switch.
#
# NOTE this DOES override the user's previous choices on `top`, deliberately and
# per the request: text/html + http(s) were vivaldi-stable, video/mp4 and
# video/webm were mpv, image/gif and video/x-matroska were umpv. Those entries
# survive in [Added Associations], so they are still one right-click →
# "Open with" away, and reverting is one edit of the list below.
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

  # Audio, to `player`. Derived from player's own AUDIO_EXTS (apps/player/main.py)
  # through shared-mime-info's globs — NOT invented — and now covering ALL
  # FOURTEEN of them, his call on docs/board.md, 2026-07-29.
  #
  # The first nine were ALREADY what the live database answers on book, with
  # nothing in this file saying so: `update-desktop-database` writes
  # player.desktop into mimeinfo.cache from its own MimeType= line, and with no
  # [Default Applications] key `xdg-mime query default` falls back to cache
  # order. Measured on book 2026-07-29 — every one of them returned
  # player.desktop already. That is an accident, not a setting: it is decided by
  # which .desktop files happen to claim the type, so installing any other audio
  # app rearranges it silently. Pinning them makes the behaviour survive.
  #
  # The rest were held back because player could not keep the promise: its Exec=
  # carries %F and `apps/player/main.py` never read a path out of sys.argv, so a
  # double-clicked track opened the library and played nothing, while the mpv and
  # elisa entries they went to instead did play what they were handed. That is
  # fixed — `paths_from_argv` / `Player.playPaths` / the queue socket's OPEN verb,
  # tested by `apps/player/tools/open-path-test.py` — so the promise is now good
  # for every extension player claims, including files OUTSIDE the library
  # (they play from a transient row that no rating or play-count write can touch).
  #
  # `audio/x-wav` and `audio/wav` are shared-mime-info ALIASES of audio/vnd.wave
  # and are listed anyway: an alias is resolved by the detector, not by
  # mimeapps.list, and `xdg-mime query default audio/x-wav` answered on book as
  # its own key. `audio/x-speex+ogg` joins the other three ogg subtypes for the
  # same reason the extension is registered at all — leaving one out would send
  # a `.ogg` to player or to mpv depending on what is inside it.
  #
  # Deliberately still absent: video/ogg and video/x-theora+ogg, which also glob
  # `.ogg`. Those are viewer's, and viewer already claims video/ogg.
  playerTypes = [
    "audio/flac" "audio/mpeg" "audio/mp4" "audio/x-m4a" "audio/ogg"
    "audio/opus" "audio/x-dsf" "audio/x-wavpack" "audio/x-ape"
    "audio/x-aiff" "audio/vnd.wave" "audio/x-wav" "audio/wav"
    "audio/x-musepack" "audio/x-tta" "audio/x-dff"
    "audio/x-vorbis+ogg" "audio/x-opus+ogg" "audio/x-flac+ogg"
    "audio/x-speex+ogg"
  ];

  # painter and board get NOTHING, on purpose. painter generates images from a
  # prompt and has no open-a-file path at all; board is a GUI over the one file
  # ~/nix/docs/board.md and is not a markdown viewer (that is reader). An app
  # with no honest file type gets no association — see board.nix's own comment.

  surferTypes = [
    "text/html" "application/xhtml+xml"
    "x-scheme-handler/http" "x-scheme-handler/https" "x-scheme-handler/about"
  ];

  # Markdown, to `reader`. This is also the WHOLE of filer's integration with
  # it: filer opens a non-image with `xdg-open`, which consults this file — so
  # a .md in filer lands in reader with no change to filer at all. Only the two
  # types shared-mime-info actually assigns to .md/.markdown are listed; plain
  # text stays with whatever the user has, because reader renders markdown and
  # is not a text editor.
  #
  # `application/pdf` joined it when reader gained its page mode: nothing on
  # this desktop claimed that type before, so a PDF out of filer reached
  # whatever xdg-open happened to guess. reader renders PDFs itself now
  # (apps/reader/pdfdoc.py), so it is the honest answer rather than a new
  # preference over an incumbent.
  readerTypes = [ "text/markdown" "text/x-markdown" "application/pdf" ];

  assoc =
    (map (t: "${t}=filer.desktop") filerTypes)
    ++ (map (t: "${t}=viewer.desktop") viewerTypes)
    ++ (map (t: "${t}=player.desktop") playerTypes)
    ++ (map (t: "${t}=surfer.desktop") surferTypes)
    ++ (map (t: "${t}=reader.desktop") readerTypes);

  setDefaults = "${pkgs.python3}/bin/python3 ${./mime-files/set-defaults.py}";
in
{
  # A default is only reached if the type is DETECTED. `xdg-open` picks a
  # detector by desktop environment, and under Hyprland it selects `generic`,
  # whose `info_generic()` is `mimetype` if that command exists and otherwise
  # `file --brief --mime-type`. `file` reads CONTENT — it has no globs — so on
  # book (Fedora's /usr/bin/xdg-open, with no `mimetype` on PATH) a `.md`
  # resolved to `text/plain`, whose default is libreoffice-writer, and
  # `text/markdown=reader.desktop` was never consulted. Measured on book
  # 2026-07-29: `xdg-mime query filetype README.md` -> text/plain, while
  # `gio info` on the same file said text/markdown.
  #
  # `mimetype` (perl File::MimeInfo) is the glob-aware detector that branch
  # wants, and it reads the shared-mime-info database from XDG_DATA_DIRS, so it
  # agrees with gio on both machines. Same measurement with it on PATH:
  # text/markdown -> reader.desktop. It fixes every glob-only type at once, not
  # just markdown (.svg, .csv were also wrong under `file`).
  #
  # THIS LINE ALONE ONLY FIXES A SHELL. It installs into the home-manager
  # profile bin dir, and on book nothing puts that on the graphical session's
  # PATH: Hyprland there is Fedora's `/usr/bin/start-hyprland`, whose PATH is
  # /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin and nothing
  # else (measured on book 2026-07-29 from /proc/<hyprland>/environ; the same
  # `xdg-mime query filetype README.md` under that PATH still says text/plain).
  # An app launched from the desktop inherits it, so the apps that shell out to
  # `xdg-open` carry `mimetype` in their own wrapper PATH — filer.nix and
  # reader.nix, on both hosts, which is the half that actually reaches him.
  # (`top` gets it for free too, its per-user profile being on the session PATH,
  # so the wrapper prefix is belt-and-braces there rather than a per-host fix.)
  home.packages = [ pkgs.perlPackages.FileMimeInfo ];

  home.activation.desktopDefaults =
    lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      run ${setDefaults} ${lib.escapeShellArgs assoc}

      # Plasma reads its own key for "the web browser" (kdeglobals
      # [General] BrowserApplication) instead of the http scheme handler, so a
      # KDE app would still have opened vivaldi. --only-if-exists keeps this a
      # no-op on book, which has no kdeglobals of its own.
      run ${setDefaults} --file kdeglobals --section General --only-if-exists \
        BrowserApplication=surfer.desktop

      # mimeapps.list alone is enough to pick the default, but mimeinfo.cache is
      # what populates "Open with…" menus — and nothing else regenerates it for
      # ~/.local/share/applications, where all six app entries are written.
      run ${pkgs.desktop-file-utils}/bin/update-desktop-database \
        "''${XDG_DATA_HOME:-$HOME/.local/share}/applications" || true
    '';

  # For anything that consults $BROWSER rather than the MIME database (git,
  # some CLI tools). Lands in hm-session-vars.sh, so it applies to shells and
  # sessions started after the next login.
  home.sessionVariables.BROWSER = "surfer";
}
