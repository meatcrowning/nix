"""Set VLC's default SFTP login without changing its other preferences."""

import re
import sys
from pathlib import Path


def configure(path, username):
    text = path.read_text() if path.exists() else ""
    section = re.search(r"(?m)^\[sftp\][^\n]*\n", text)
    setting = f"sftp-user={username}\n"
    if section:
        end = re.search(r"(?m)^\[", text[section.end():])
        stop = section.end() + end.start() if end else len(text)
        body = text[section.end():stop]
        body = re.sub(r"(?m)^#?sftp-user=[^\n]*(?:\n|$)", "", body)
        text = text[:section.end()] + setting + body + text[stop:]
    else:
        text += "\n[sftp]\n" + setting
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


if __name__ == "__main__":
    configure(Path(sys.argv[1]), sys.argv[2])
