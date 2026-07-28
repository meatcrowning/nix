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
  readerTypes = [ "text/markdown" "text/x-markdown" ];

  assoc =
    (map (t: "${t}=filer.desktop") filerTypes)
    ++ (map (t: "${t}=viewer.desktop") viewerTypes)
    ++ (map (t: "${t}=surfer.desktop") surferTypes)
    ++ (map (t: "${t}=reader.desktop") readerTypes);

  setDefaults = "${pkgs.python3}/bin/python3 ${./mime-files/set-defaults.py}";
in
{
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
