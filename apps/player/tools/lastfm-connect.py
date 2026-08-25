#!/usr/bin/env python3
"""Link a Last.fm account to this desktop — once, for player AND chatter.

    tools/lastfm-connect.py --keys API_KEY API_SECRET   # first time only
    tools/lastfm-connect.py                             # approve in a browser
    tools/lastfm-connect.py --copy-from top             # take top's account
    tools/lastfm-connect.py --status                    # who is linked
    tools/lastfm-connect.py --disconnect                # drop the session

Both halves are needed and they are separate acts. The API key and secret
identify the PROGRAM and come from an API account he creates once, at
https://www.last.fm/api/account/create — they cannot be shipped, because
`~/nix` is a public repo (root AGENTS.md). The session key identifies the
ACCOUNT and comes from him approving a token in a browser he is already
logged into.

Everything lands in `~/.config/lastfm/account.json` (0600), which is the one
file `apps/pylib/lastfm.py` reads. player picks it up at launch; chatter
re-reads it per call, so a connect made while chatter is open just works.
"""
import argparse
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pylib"))
import lastfm  # noqa: E402


def cmd_status():
    st = lastfm.status()
    if not st["keys"]:
        print("no API key/secret yet — create one at\n  " + lastfm.CREATE_PAGE
              + "\nthen: tools/lastfm-connect.py --keys KEY SECRET")
        return 1
    if not st["connected"]:
        print("API key configured, no account linked yet — run this with no "
              "arguments")
        return 1
    print("linked as %s" % st["username"])
    if st["queued"]:
        print("%d scrobble(s) waiting to go out" % st["queued"])
    print("file: %s" % lastfm.CONFIG_PATH)
    return 0


def cmd_keys(key, secret):
    lastfm.save(api_key=key.strip(), api_secret=secret.strip())
    print("wrote the API key and secret to %s" % lastfm.CONFIG_PATH)
    return 0


def cmd_copy_from(host):
    """Take the linked account off the OTHER machine.

    The account file is machine-local by design — it is a credential and `~/nix`
    is public, so it syncs with nothing — which meant player on book scrobbled
    nothing at all while top had been linked for months [his, 2026-08-24: *"wire
    up lastfm support in player on air"*]. Approving a second token in a browser
    works too; this is the one that needs neither a browser nor his attention.

    It is a `cat` over ssh rather than scp so it works with the same BatchMode
    key and MagicDNS name everything else here uses, and the file lands 0600.
    Nothing is written unless what came back parses as an account.
    """
    import json
    import os
    import subprocess
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
             "cat " + str(lastfm.CONFIG_PATH)],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print("could not reach %s: %s" % (host, e), file=sys.stderr)
        return 1
    if out.returncode != 0 or not out.stdout.strip():
        print("nothing came back from %s: %s"
              % (host, (out.stderr or "").strip() or "no account file there"),
              file=sys.stderr)
        return 1
    try:
        data = json.loads(out.stdout)
        if not isinstance(data, dict) or not data.get("api_key"):
            raise ValueError("no api_key in it")
    except ValueError as e:
        print("what came back is not an account file: %s" % e, file=sys.stderr)
        return 1
    path = Path(lastfm.CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(path, 0o600)
    who = data.get("username") or "(no session key — approve one here)"
    print("copied %s's account to %s\nlinked as %s" % (host, path, who))
    return 0


def cmd_disconnect():
    name = lastfm.username()
    lastfm.forget_session()
    print("disconnected%s — the API key is kept, so reconnecting is one "
          "approval" % (" " + name if name else ""))
    return 0


def cmd_connect(open_browser=True, wait=180):
    if not lastfm.has_keys():
        print("no API key/secret yet. Create an API account at\n  "
              + lastfm.CREATE_PAGE
              + "\n(callback URL can be left blank for a desktop app), then\n"
              "  tools/lastfm-connect.py --keys YOUR_KEY YOUR_SECRET",
              file=sys.stderr)
        return 1
    try:
        token = lastfm.get_token()
    except lastfm.LastfmError as e:
        print("could not get a request token: %s" % e, file=sys.stderr)
        return 1
    url = lastfm.auth_url(token)
    print("approve this desktop here:\n  %s\n" % url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # Poll rather than ask him to press a key: auth.getSession answers error
    # 14 until the token is authorized, so the flow finishes by itself the
    # moment he clicks yes.
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            key, name = lastfm.get_session(token)
        except lastfm.LastfmError as e:
            if e.code == 14:          # not authorized yet
                time.sleep(3)
                continue
            print("failed: %s" % e, file=sys.stderr)
            return 1
        lastfm.save(session_key=key, username=name)
        print("linked as %s" % name)
        return 0
    print("timed out waiting for approval — run it again", file=sys.stderr)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keys", nargs=2, metavar=("API_KEY", "API_SECRET"),
                    help="store the API key and shared secret, then exit")
    ap.add_argument("--status", action="store_true", help="who is linked")
    ap.add_argument("--copy-from", metavar="HOST",
                    help="take the linked account off another machine "
                         "(e.g. --copy-from top), instead of approving a "
                         "second token in a browser")
    ap.add_argument("--disconnect", action="store_true",
                    help="drop the session key, keep the API key")
    ap.add_argument("--no-browser", action="store_true",
                    help="print the approval URL instead of opening it")
    ap.add_argument("--wait", type=int, default=180,
                    help="seconds to wait for the approval (default 180)")
    a = ap.parse_args()
    if a.keys:
        return cmd_keys(*a.keys)
    if a.status:
        return cmd_status()
    if a.copy_from:
        return cmd_copy_from(a.copy_from)
    if a.disconnect:
        return cmd_disconnect()
    return cmd_connect(open_browser=not a.no_browser, wait=a.wait)


if __name__ == "__main__":
    sys.exit(main())
