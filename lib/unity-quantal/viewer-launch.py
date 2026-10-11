"""Native viewer entry point; legacy-only formats keep their isolated reader."""
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit
import isolated

# Select the reader before decoding, never retry a failed native decode in an
# obsolete library. These six loaders were removed from current GdkPixbuf.
LEGACY_SUFFIXES = {".pcx", ".wmf", ".apm", ".wbmp", ".ras", ".sun", ".ani", ".jp2", ".jpc", ".j2k", ".jpf", ".jpx"}
LEGACY_FLAGS = {"--new-instance", "-n", "--fullscreen", "-f", "--slide-show", "-s", "--disable-gallery", "-g"}


def legacy_arguments(arguments):
    files, flags = [], []
    positional = False
    for value in arguments:
        if not positional and value == "--":
            positional = True
        elif not positional and value.startswith("-"):
            if value not in LEGACY_FLAGS:
                return None
            flags.append(value)
        else:
            files.append(value)
    try:
        paths = [Path(unquote(urlsplit(value).path) if value.startswith("file:") else value) for value in files]
    except ValueError:
        return None  # Let EOG report invalid arguments in its usual way.
    if not any(path.suffix.lower() in LEGACY_SUFFIXES and not path.is_dir() for path in paths):
        return None
    return files, flags


def main(arguments):
    legacy = legacy_arguments(arguments)
    if legacy is not None:
        files, flags = legacy
        try:
            isolated.main("eog", files, viewer_flags=flags)
        except Exception as error:
            print(str(error), file=sys.stderr)
            isolated.dialog("--error", "--no-markup", "--title=Application could not finish", "--text=" + str(error))
            raise SystemExit(1) from error
    else:
        executable = isolated.CONFIG["viewer"]
        os.execv(executable, [executable, *arguments])


if __name__ == "__main__":
    main(sys.argv[1:])
