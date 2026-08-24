#!/usr/bin/env python3
"""oracle — a deliberately small chat window for the local ollama daemon.

The twelfth vendored app, and the plainest: a MODEL SELECTOR filled from the
ollama daemon's own `/api/tags`, and a PROMPT BOX that sends one chat turn to
`/api/chat` and shows the streamed reply. Nothing more — no history persistence,
no settings, no system prompt. It exists to talk to `http://127.0.0.1:11434`
and get out of the way.

It draws like the rest of the desktop rather than choosing anything here: pixel
font at the desktop's own size through `DeskStyle`, the wal palette parsed and
watched out of the panel's `Theme.qml` (mirrors reader/filer/viewer), motion
from `qmlcommon/Motion.qml`, `Kinetic*` views, and its titlebar chrome drawn by
the hyprvtb compositor plugin through `pylib/vtbclient.py` — see docs/DESIGN.md.

The whole ollama seam is `Ollama` below, on `QNetworkAccessManager`: `/api/tags`
for the model list, and a STREAMING `/api/chat` POST whose NDJSON reply is
parsed line by line and emitted as it arrives, so the reply grows on screen the
way it comes off the model.
"""
import base64
import hashlib
import io
import json
import os
import platform
import re
import shutil
import socket
import sys
import tarfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import shlex
from html.parser import HTMLParser

from PySide6.QtCore import (QObject, Slot, Signal, Property, QUrl, QUrlQuery,
                            QBuffer, QFileSystemWatcher, QProcess,
                            QProcessEnvironment, Qt, QTimer)
from PySide6.QtGui import QGuiApplication, QColor, QImage
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkRequest,
                               QNetworkReply)
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
# Imported for its side effect: it registers the QtQuick wrapper types, so the
# QML root arrives as a QQuickWindow rather than a bare QWindow — which is what
# the selftest's `grabWindow()` needs.
from PySide6.QtQuick import QQuickWindow  # noqa: F401

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"
#: Files onto the Wayland clipboard, as files — see `Clip.copyImage` for why a
#: subprocess and never QClipboard (apps/pylib/clipfile.py).
CLIPFILE = HERE.parent / "pylib" / "clipfile.py"

# HIS FILES ARE NOT THE HARNESS'S, and this has to happen before the store paths
# below are computed — hence up here rather than in `main()`. Poking the
# Settings menu calls `setPromptChoice`, which PERSISTS, so a selftest run with
# no override rewrote his own base prompt (root AGENTS.md → "Testing without
# interfering with the user"). Both stores go somewhere disposable unless the
# caller has already said where.
#: A harness is driving this window offscreen — see `Backend._systemctl`, and
#: `run_selftest` at the bottom of this file.
SELFTEST = "--selftest" in sys.argv

if "--selftest" in sys.argv:
    _tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "oracle-selftest"
    os.environ.setdefault("ORACLE_CONFIG", str(_tmp / "config"))
    os.environ.setdefault("ORACLE_SESSIONS", str(_tmp / "sessions"))
    os.environ.setdefault("ORACLE_IMAGES", str(_tmp / "images"))

sys.path.insert(0, str(HERE.parent / "pylib"))
from vtbclient import VtbClient  # noqa: E402  (needs the path insert above)
from warden import Warden  # noqa: E402  (same)
from deskstyle import DeskStyle  # noqa: E402  (pylib; the desktop-wide font setting)
from kdetheme import theme_source, is_plasma  # noqa: E402  (pylib; the KDE global theme in a Plasma session)
import kdeshell  # noqa: E402  (pylib; the Plasma session's real QtWidgets window)
import lastfm as lastfmlib  # noqa: E402  (pylib; his Last.fm account, shared with player)
import genshort  # noqa: E402  (his generation shorthand -> make_image/make_video args)
import boorutags  # noqa: E402  (pylib; the Danbooru vocabulary anima was captioned with)

#: The local ollama daemon. Loopback-pinned like everything else that speaks to
#: a local backend here — never a new listener (root AGENTS.md → the tailnet).
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

#: Tavily's REST search endpoint. Reached only when the model calls the
#: `web_search` tool AND a key is configured — oracle opens no listener, and
#: without a key the tool reports itself unavailable rather than reaching out.
TAVILY_URL = "https://api.tavily.com/search"

#: The web-search tool offered to ollama on EVERY turn (his call — no toggle,
#: same as the file tools). ollama's function-calling: the model may emit a
#: `tool_calls` entry naming this and we run it, feed the result back as a
#: `role: tool` message, and let the model summarize and cite (the loop lives in
#: `Ollama` below).
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for current or factual information you may "
            "not know. Returns a short answer plus source pages (title, URL, "
            "snippet). Use it for recent events, specific facts, or anything "
            "you are unsure of, then cite the sources in your reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "The search query."},
            },
            "required": ["query"],
        },
    },
}

#: The IMAGE-FETCH tool, offered on every turn beside the web/file/time tools.
#: The model calls it with a direct image URL; oracle downloads the bytes,
#: verifies they decode as an image, saves them LOCALLY and hands the local path
#: to QML, which renders the picture inline in the chat log (the one place a
#: model reply becomes a picture rather than text). Failure is surfaced, never
#: swallowed (docs/DESIGN.md §10): a non-URL, a non-image response and an
#: undecodable body each come back as a visible error line AND a tool error the
#: model sees. Unlike the file/session/memory stores this does NOT run on top —
#: the image must be a local file the QML Image element can load, and the fetch
#: is a plain in-process web GET, so it runs wherever the window is (see FETCH
#: below).
IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_image",
        "description": (
            "Download an image from a public web URL and DISPLAY it inline in the "
            "chat for the user to see. Use it when he asks to see a picture, "
            "photo, chart, diagram or logo, or when showing an image makes your "
            "answer clearer. Pass the DIRECT url of an image file (one that "
            "returns image data — typically ending in .png/.jpg/.jpeg/.gif/.webp); "
            "a link to a web PAGE will not work. Do NOT guess or invent an image "
            "URL — if you do not already have a real one, call search_images "
            "first and pass a url it returns. The image is shown to him "
            "automatically, so you need not describe it unless he asks. If the "
            "fetch fails you get an error back and nothing is shown — tell him."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string",
                    "description": "Direct URL of the image file to download."},
            "alt": {"type": "string",
                    "description": "A short caption describing the image (optional)."}},
            "required": ["url"]}},
}
IMAGE_TOOL_NAMES = {"fetch_image"}

#: The LOCAL-IMAGE tool — the model LOOKS AT a picture on the machine, the same
#: way it sees one he drags onto the window [his, 2026-08-22]. `read_file`
#: reaches every file on the box but hands back TEXT, so an image was a wall:
#: the model could find `holiday.jpg`, could not see a pixel of it, and said so
#: only if it was honest. This closes that: the bytes come back through the same
#: jailed executor (`sandbox-fs.py` op `image`, the WIDE read root, sniffed by
#: magic and capped), are attached to the NEXT message of the tool loop as an
#: ollama vision `images` block, and are drawn inline in the chat so he sees
#: exactly what it was shown (docs/DESIGN.md §10 — nothing looked at in secret).
VIEW_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "view_image",
        "description": (
            "LOOK AT an image file on this machine — a photo, a screenshot, a "
            "diagram — and see it for yourself. Use it whenever answering "
            "involves what a local picture actually shows: he names a file, you "
            "found one with find_files/list_dir, or he asks what is in an image. "
            "read_file cannot do this: it returns text and an image is bytes. "
            "Pass the path (absolute, or as list_dir gave it). The picture is "
            "attached to your next turn — so after calling this, WAIT for it and "
            "then describe or use what you see. It is also shown to him in the "
            "chat, so you need not describe it unless he asks. Needs a "
            "vision-capable model; png, jpeg, gif and webp, up to 8 MB."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "Path of the image file to look at."},
            "host": {"type": "string",
                     "description": ("Which machine to read from: 'top' or "
                                     "'book'. Defaults to this one.")}},
            "required": ["path"]}},
}
VIEW_IMAGE_TOOL_NAMES = {"view_image"}

#: SHOWING is not LOOKING [his, 2026-08-23]. Until now the only way to put a
#: local picture in the chat was `view_image`, which is a VISION tool: it needs
#: a vision-capable model, reads the whole file, and spends 8 MB of context on
#: base64 the model then has to think about — all to display a graph it had just
#: drawn itself. This is the other half: the picture goes on screen and NOTHING
#: goes to the model, so a coding model with no vision can still plot something
#: and show it.
SHOW_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "show_image",
        "description": (
            "DISPLAY an image file in the chat for him to look at. Use it "
            "whenever you have made or found a picture on this machine and he "
            "should see it — a chart or graph you just plotted, a screenshot, a "
            "diagram, a photo he asked you to find on disk. This does NOT show "
            "it to you: it costs you nothing and needs no vision support. If "
            "you also need to SEE it yourself, use view_image instead (or as "
            "well). Say what the picture shows in your reply if it needs "
            "saying; do not describe it as though you had looked at it."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "Path of the image file to display."},
            "caption": {"type": "string",
                        "description": "A short caption drawn under it (optional)."},
            "host": {"type": "string", "enum": ["top", "book"],
                     "description": ("Which machine the file is on. Default: "
                                     "the one this window runs on.")}},
            "required": ["path"]}},
}
SHOW_IMAGE_TOOL_NAMES = {"show_image"}

#: THE SCREEN, as a picture [his, 2026-08-23]. `grim` under Hyprland, Spectacle
#: under Plasma; the frame lands in IMAGES_ROOT, is drawn in the chat so he sees
#: exactly what was captured (docs/DESIGN.md §10 — nothing looked at in secret),
#: and is attached to the model's next turn when the model has vision. NOTE the
#: boundary this does NOT cross: root AGENTS.md forbids an AGENT'S TEST from
#: screenshotting his session. This is the opposite direction — he asked the app
#: for it, at his own keystroke — and no harness may call it.
SCREENSHOT_TOOL = {
    "type": "function",
    "function": {
        "name": "screenshot",
        "description": (
            "Take a picture of his screen right now and LOOK at it. Use it when "
            "the question is about what is on screen — 'what does this error "
            "say', 'what am I looking at', 'is this laid out right' — or when "
            "he asks you to look at his screen. The capture is shown in the "
            "chat as well, so he sees exactly what you were shown. It is "
            "attached to your NEXT turn, so after calling this, wait for it and "
            "then answer from what you see. Needs a vision-capable model."),
        "parameters": {"type": "object", "properties": {
            "show_only": {"type": "boolean",
                          "description": ("Only put it in the chat, do not send "
                                          "it to you. Use when he just wants a "
                                          "screenshot saved.")}},
            "required": []}},
}
SCREENSHOT_TOOL_NAMES = {"screenshot"}

#: MAKING a picture, not fetching one [his, 2026-08-23]. painter's backend is
#: already on `top` — ComfyUI, 246 GB of weights, and `painter/tools/smoke.py`,
#: which is painter's OWN registry/graph/client path with the GUI taken off. So
#: this tool is that script, run where the weights are, and the result drawn in
#: the chat: chatter builds no graph of its own and knows nothing about models,
#: which is what keeps the two from drifting.
#:
#: It reserves through the ai-warden first (`apps/pylib/warden.py`): ollama and
#: ComfyUI share 31 GiB and a collision livelocks the machine rather than
#: failing, so a generation asks for room and takes "no, and here is why" for an
#: answer (home/srvs/ai-warden.nix).
MAKE_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "make_image",
        "description": (
            "GENERATE or EDIT a picture on his own machine and show it in the "
            "chat. Use it when he asks you to draw, generate, imagine or make "
            "an image, or to change one he has given you — not when he wants a "
            "real photograph of something that exists, which is search_images "
            "plus fetch_image. Write the prompt the way an image model wants "
            "it: subject first, then the concrete visual details, then style "
            "and lighting; commas, not sentences. Pass his own tags through "
            "VERBATIM — never rewrite a danbooru-style tag list. Give "
            "input_images to EDIT those pictures instead of generating a fresh "
            "one (that switches to the edit model on its own). For the ANIME "
            "model (anima) ALWAYS call use_skill('anima-prompt') first — once "
            "per conversation is enough — and look tags up with "
            "booru_tags before you write them — an invented tag does nothing — "
            "write them with spaces and an artist as @name, and NEVER open with "
            "'masterpiece, best quality' or a score_ tag: he does not prompt "
            "that way. Name a CHARACTER by its tag plus its series tag and let "
            "those carry the appearance — do not describe hair and eyes from "
            "memory. Write your own `negative` for the picture; on that model "
            "it is folded into the positive as an inline negative weight with "
            "its own box left empty. PASS ONLY WHAT "
            "HE ASKED FOR: every argument you leave out falls back to what he "
            "himself set in painter for that model — size, steps, sampler, his "
            "own negative prompt — which is what he wants unless he says "
            "otherwise. This takes "
            "anywhere from twenty seconds to a few minutes, so call it ONCE and "
            "wait. He sees the picture; you do not, unless you view_image it "
            "afterwards."),
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string",
                       "description": "What to draw, as image-model prompt text."},
            "negative": {"type": "string",
                         "description": "What to keep out of it (optional)."},
            "model": {"type": "string",
                      "description": ("Part of a model name, e.g. 'anima' "
                                      "(anime), 'krea' (photoreal), 'klein' "
                                      "(editing), 'chroma', 'z_image', 'qwen'. "
                                      "Omit for his default.")},
            "input_images": {"type": "array", "items": {"type": "string"},
                             "description": ("Local paths of pictures to EDIT. "
                                             "The first one is the subject and "
                                             "sets the output size; the rest are "
                                             "references. Omit to generate "
                                             "fresh.")},
            "aspect": {"type": "string",
                       "description": ("Aspect ratio as W:H, e.g. '2:3', '16:9' "
                                       "(optional; ignored when editing).")},
            "megapixels": {"type": "number",
                           "description": ("Output size in megapixels, e.g. 1 or "
                                           "2 (optional).")},
            "count": {"type": "integer",
                      "description": "How many to make in one go (optional, default 1)."},
            "width": {"type": "integer", "description": "Pixels (optional; overrides aspect)."},
            "height": {"type": "integer", "description": "Pixels (optional; overrides aspect)."},
            "seed": {"type": "integer",
                     "description": "Fixed seed, for a repeatable picture (optional)."},
            "steps": {"type": "integer", "description": "Sampling steps (optional)."}},
            "required": ["prompt"]}},
}
MAKE_IMAGE_TOOL_NAMES = {"make_image"}

#: painter's headless generator, and how long one picture may take. The command
#: starts the backend if it is down (it is a user unit, and a `start` on a
#: running one is a no-op), waits for it to answer, and only then generates —
#: which is what painter's own launcher does on book (home/prog/painter.nix).
PAINTER_SMOKE = "/home/lam/nix/apps/painter/tools/smoke.py"
MAKE_IMAGE_MS = 15 * 60 * 1000
#: A CLIP is the same act on a much longer clock — MiniMax H3 samples every
#: frame, so six seconds is tens of minutes on this GPU, not one. The ceiling is
#: what stops a wedged backend holding the warden lease for ever, so it is
#: generous rather than tight.
MAKE_VIDEO_MS = 60 * 60 * 1000
#: What a generated clip looks like on disk, so the video branch can tell
#: its own output from a still the same graph also saved.
VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv", ".mov")

#: The memory reservation a generation holds, and how often it says it is still
#: working (home/srvs/ai-warden-files/ai-warden.py). Short + renewed, never long
#: + taken once: the interval is what a chatter that dies mid-render costs the
#: other side, and the ceiling would otherwise be an hour of blocked painter.
WARDEN_LEASE_S = 300
WARDEN_BEAT_MS = 120 * 1000

#: The VIDEO-GENERATION tool. Same backend, same warden, same generator script
#: as `make_image` — what differs is the model family (a video one), the clock
#: above, and that the result is drawn as a VideoCard rather than an image.
#: Image-to-video is the shape he actually uses: a picture he pasted becomes the
#: first frame, and the prompt says what happens next.
MAKE_VIDEO_TOOL = {
    "type": "function",
    "function": {
        "name": "make_video",
        "description": (
            "GENERATE a short video on his own machine and put it in the chat. "
            "Use it when he asks for a video, a clip or an animation. Give "
            "first_frame (a local image path — one he attached, or one you "
            "made) to animate FROM that picture, which is the usual case; give "
            "last_frame as well to make the clip land on a second picture; give "
            "neither for text-to-video. Write the prompt as motion: what moves, "
            "how the camera moves, what changes over the clip. PASS ONLY WHAT "
            "HE ASKED FOR: every argument you leave out falls back to what he "
            "himself set in painter — length, size, steps, sampler. This is SLOW — "
            "many minutes for a few seconds of video — so call it ONCE, wait, "
            "and do not offer to do it again while it runs. He sees the clip; "
            "you do not."),
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string",
                       "description": "What happens in the clip, as motion."},
            "first_frame": {"type": "string",
                            "description": ("Local path of the image to start "
                                            "from (optional).")},
            "last_frame": {"type": "string",
                           "description": ("Local path of the image to end on "
                                           "(optional). The same file in both "
                                           "makes it loop.")},
            "seconds": {"type": "number",
                        "description": "How long, in seconds (optional, default 5)."},
            "model": {"type": "string",
                      "description": ("Part of a video model's name, e.g. "
                                      "'minimax'. Omit for his default.")},
            "aspect": {"type": "string",
                       "description": ("Aspect ratio as W:H (optional; ignored "
                                       "when a frame is given — the picture "
                                       "decides).")},
            "megapixels": {"type": "number",
                           "description": "Frame size in megapixels (optional)."},
            "seed": {"type": "integer", "description": "Fixed seed (optional)."},
            "steps": {"type": "integer", "description": "Sampling steps (optional)."}},
            "required": ["prompt"]}},
}
MAKE_VIDEO_TOOL_NAMES = {"make_video"}

#: THE DANBOORU VOCABULARY, as a tool [his, 2026-08-24: "give it a list of all
#: danbooru tags to draw from when prompting with anima"]. Anima was captioned
#: with Danbooru's tags, and a tag the site does not have does nothing — it is
#: not a weaker version of the tag you meant, it is noise the model has never
#: seen. A model writing from memory invents plausible ones at a steady rate, so
#: the 91k-tag list ships with the apps (`pylib/boorutags.py`) and is SEARCHED
#: rather than pasted: a whole vocabulary in the context would be 2 MB and still
#: not tell it which tag is the used one.
BOORU_TOOL = {
    "type": "function",
    "function": {
        "name": "booru_tags",
        "description": (
            "Look up real Danbooru tags — the vocabulary the anime model "
            "(anima) was trained on. Use it whenever you write an anime/anima "
            "prompt: search for the tag you mean before you write it, because "
            "a tag that is not on the list does NOTHING in the picture, and "
            "check a prompt you have drafted to catch the ones you invented. "
            "It also resolves what he half-remembered — 'sole female' comes "
            "back as '1girl'. Answers carry the tag's category: an ARTIST is "
            "written '@name' in the prompt, a CHARACTER wants its series "
            "beside it. Write tags with spaces, not underscores."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string",
                      "description": ("What to look for, e.g. 'windowsill', "
                                      "'looking at viewer', 'toi8'.")},
            "check": {"type": "string",
                      "description": ("A whole draft prompt to check instead — "
                                      "returns which tags are real, which were "
                                      "renamed, and which do not exist.")},
            "category": {"type": "string",
                         "description": ("Narrow a search: general, artist, "
                                         "character, copyright, meta.")},
            "limit": {"type": "integer",
                      "description": "How many to return (default 25)."}},
            "required": []}},
}
BOORU_TOOL_NAMES = {"booru_tags"}

#: The IMAGE-SEARCH tool. fetch_image can only GET a URL the model already has,
#: and a model asked for "a picture of X" tends to GUESS a plausible-looking
#: image URL that 404s — the fetch then honestly fails, but no picture shows.
#: This closes that gap: it searches the web (Tavily, include_images) and returns
#: REAL direct image URLs the model can then hand straight to fetch_image, so a
#: "show me X" actually resolves instead of relying on a hallucinated link.
SEARCH_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_images",
        "description": (
            "Find real image URLs on the web for a subject. Use this FIRST "
            "whenever he asks to see a picture/photo/logo of something and you do "
            "not already have a known-good direct image URL — do NOT guess or "
            "invent an image URL, they will not load. Returns a list of direct "
            "image URLs (with short descriptions). Pick the best match and pass "
            "its url to fetch_image to display it."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "What to find an image of, e.g. 'spongebob "
                      "squarepants' or 'mount fuji at sunrise'."}},
            "required": ["query"]}},
}
SEARCH_IMAGE_TOOL_NAMES = {"search_images"}

#: The VIDEO tool. fetch_image made a reply able to show a picture; this makes it
#: able to show a MOVING one — a clip from a direct media URL, or from a YouTube
#: (or any other yt-dlp-supported) watch page, played inline in the bubble.
#: Nothing is downloaded: what the tool produces is a STREAM URL that
#: QtMultimedia's ffmpeg backend pulls off the network itself, so a 200 MB video
#: costs no disk and no wait before it appears. It never autoplays — the card
#: sits on its poster frame under a play marker until he clicks it, because
#: nothing on this desktop starts making noise on its own (docs/DESIGN.md §13),
#: and because he listens to music while he works.
VIDEO_TOOL = {
    "type": "function",
    "function": {
        "name": "show_video",
        "description": (
            "Show a video inline in the chat for the user to watch. Use it when "
            "he asks to see a video or a clip, when he gives you a link to one, "
            "or when a video is the answer. Unlike fetch_image this accepts a "
            "web PAGE: a YouTube or Vimeo watch URL works, and so does a direct "
            "link to a video file (.mp4/.webm/.mkv). Do NOT invent a YouTube id "
            "or link — they will not resolve; search the web for the real one "
            "first and pass what you find. The video is placed in the chat with "
            "its title and a play button and does NOT start on its own, so tell "
            "him it is there. If it cannot be resolved you get an error back "
            "and nothing is shown — tell him that too."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string",
                    "description": ("The video's URL — a watch page (YouTube, "
                                    "Vimeo, …) or a direct video file.")},
            "alt": {"type": "string",
                    "description": ("A short caption of your own (optional — the "
                                    "site's own title is used when you give none).")}},
            "required": ["url"]}},
}
VIDEO_TOOL_NAMES = {"show_video"}

#: THE MUSIC PLAYER, as a tool [his, 2026-08-23: *"give agents the ability to
#: manipulate playback of player"*]. `apps/player` publishes the standard MPRIS
#: interface (`org.mpris.MediaPlayer2.player`, the same one the panel's media
#: widget drives), so this needs no new seam in the player at all — it is the
#: session bus of the machine the WINDOW runs on, which is why it says so
#: honestly when nothing is playing there (his music lives on `top`).
#:
#: What it offers is what the player actually implements: MPRIS `Stop` and
#: `OpenUri` are no-ops in its adapter, so neither is offered as an action that
#: would silently do nothing (docs/DESIGN.md §10). Every action answers with the
#: resulting STATUS, so the model sees what it did rather than assuming.
PLAYER_TOOL = {
    "type": "function",
    "function": {
        "name": "control_media",
        "description": (
            "See and control ANY media playing on this machine — his `player` "
            "app, a browser tab, mpv, anything that speaks MPRIS. `status` "
            "tells you what is playing (title, artist, album, how far in, how "
            "long, which player, and the SYSTEM volume), `list` names every "
            "player on the bus, and every other action does the thing and then "
            "tells you the same. `volume` sets the machine's volume, not the "
            "app's — his player exposes none, so its own number is meaningless. "
            "Use it when he asks what is playing, or asks you to pause it, skip "
            "it, go back, jump to a point, mute, or change the volume. Every "
            "action returns the resulting status, so never guess what happened; "
            "and if nothing is playing you are told that plainly."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["status", "list", "play", "pause", "play_pause",
                                "next", "previous", "seek", "volume", "mute",
                                "shuffle", "loop", "play_these", "queue_these"],
                       "description": ("What to do. `status` changes nothing; "
                                       "`play_these` replaces the queue with "
                                       "`paths` and starts it, `queue_these` "
                                       "appends them.")},
            "seconds": {"type": "number",
                        "description": ("For `seek`: where to jump to, in "
                                        "seconds from the start — or how far to "
                                        "jump (negative for back) when "
                                        "`relative` is true.")},
            "relative": {"type": "boolean",
                         "description": "For `seek`: jump BY `seconds` rather than TO it."},
            "level": {"type": "integer",
                      "description": ("For `volume`: 0-100, the SYSTEM volume "
                                      "unless `scope` says otherwise.")},
            "player": {"type": "string",
                       "description": ("Which player, as `list` names them — "
                                       "e.g. 'player', 'vivaldi', 'mpv'. "
                                       "Leave it out for his music player, or "
                                       "whatever else is playing.")},
            "scope": {"type": "string", "enum": ["system", "player"],
                      "description": ("For `volume`: the machine's mixer "
                                      "(default) or that one player's own.")},
            "on": {"type": "boolean",
                   "description": "For `mute`: mute (true) or unmute (false)."},
            "on": {"type": "boolean", "description": "For `shuffle`: on or off."},
            "mode": {"type": "string", "enum": ["none", "track", "playlist"],
                     "description": "For `loop`: repeat nothing, this track, or the queue."},
            "paths": {"type": "array", "items": {"type": "string"},
                      "description": ("For `play_these` / `queue_these`: track "
                                      "file paths, as music_library returns "
                                      "them. An album is its tracks in order.")}},
            "required": ["action"]}},
}
#: Both names answer: `control_player` is what every earlier session, every
#: agent definition and his own habit call it, and a rename that broke those
#: would be a rename that cost him something.
PLAYER_TOOL_NAMES = {"control_media", "control_player"}

#: THE LIBRARY, not just the transport [his, 2026-08-23: *"are agents able to
#: easily browse and play music from my library?"*]. They were not: MPRIS
#: carries the current track and nothing else, so `control_player` could skip
#: and pause but could not answer "what have I got" or "put that album on".
#: `apps/player/tools/library-ipc.py` is the other half — a READ-ONLY sqlite
#: query against player's own library plus the two queue verbs on its socket —
#: and it runs where the library is (top), reached exactly like the file
#: executor.
MUSIC_TOOL = {
    "type": "function",
    "function": {
        "name": "music_library",
        "description": (
            "Search his music library — 19,000-odd tracks, with their artists, "
            "albums, ratings, favourites and play counts. `search` matches free "
            "text against title, artist and album at once (how a person names "
            "music), `albums` lists albums, `album_tracks` gives one album in "
            "play order, `stats` sizes the library. Every track comes back with "
            "its `path`, which is what control_media's play_these / "
            "queue_these take — so 'put on X' is this tool and then that one. "
            "Read-only: it never changes a rating, a tag or a play count."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["search", "albums", "album_tracks", "stats"],
                       "description": "What to ask for. Default `search`."},
            "query": {"type": "string",
                      "description": "Free text: part of a title, artist or album."},
            "artist": {"type": "string", "description": "Narrow to an artist."},
            "album": {"type": "string",
                      "description": "The album — required for `album_tracks`."},
            "genre": {"type": "string", "description": "Narrow to a genre."},
            "favorites_only": {"type": "boolean",
                               "description": "Only tracks he has hearted."},
            "min_rating": {"type": "integer",
                           "description": "Only tracks rated at least this (1-5)."},
            "sort": {"type": "string",
                     "enum": ["artist", "album", "title", "rating", "plays",
                              "recent", "played", "random"],
                     "description": "Order. `random` is how you pick something new."},
            "limit": {"type": "integer", "description": "Rows to return (max 60)."},
            "offset": {"type": "integer", "description": "Skip this many, to page."}},
            "required": []}},
}
MUSIC_TOOL_NAMES = {"music_library"}

#: ---- last.fm: what he has ACTUALLY listened to --------------------------
#: `music_library` answers "what does he own"; this answers "what does he
#: play", which is a different question and the one a recommendation needs.
#: The account is linked once by `apps/player/tools/lastfm-connect.py` and the
#: credentials live in `~/.config/lastfm/account.json` (`pylib/lastfm.py`) —
#: player scrobbles into the same account, so a tool call here reads the
#: history that player has been writing.
#:
#: Read plus the two loves, and nothing else. `love`/`unlove` are the only
#: writes offered because they are HIS gesture, reversible in one call, and
#: the same one the player's heart makes; there is deliberately no scrobble
#: action, since a model inventing plays would corrupt the very history the
#: read actions exist to consult.
LASTFM_ACTIONS = {
    # action: (method, [required args], unsigned)
    "recent":            ("user.getRecentTracks", [], False),
    "top_artists":       ("user.getTopArtists", [], False),
    "top_albums":        ("user.getTopAlbums", [], False),
    "top_tracks":        ("user.getTopTracks", [], False),
    "loved":             ("user.getLovedTracks", [], False),
    "user_info":         ("user.getInfo", [], False),
    "artist_info":       ("artist.getInfo", ["artist"], False),
    "similar_artists":   ("artist.getSimilar", ["artist"], False),
    "artist_top_tracks": ("artist.getTopTracks", ["artist"], False),
    "artist_top_albums": ("artist.getTopAlbums", ["artist"], False),
    "similar_tracks":    ("track.getSimilar", ["artist", "track"], False),
    "track_info":        ("track.getInfo", ["artist", "track"], False),
    "album_info":        ("album.getInfo", ["artist", "album"], False),
    "tag_top_artists":   ("tag.getTopArtists", ["tag"], False),
    "tag_top_tracks":    ("tag.getTopTracks", ["tag"], False),
    "search_artist":     ("artist.search", ["artist"], False),
    "search_track":      ("track.search", ["track"], False),
    "love":              ("track.love", ["artist", "track"], True),
    "unlove":            ("track.unlove", ["artist", "track"], True),
}
#: Periods user.getTop* accepts. Named in the schema so a model cannot invent
#: one and get a silent overall chart back.
LASTFM_PERIODS = ["overall", "7day", "1month", "3month", "6month", "12month"]
#: Caps, his rule 5. Rows first, then a hard character cap on the projection —
#: an artist.getInfo carries a whole biography and a tag chart carries a
#: hundred of them.
LASTFM_MAX_ROWS = 50
LASTFM_CHARS = 12000
LASTFM_STR_CHARS = 700
#: Dropped from every row before the model sees it: image URL sets (five
#: sizes of the same picture, per row) and the streamable/tracking flags.
LASTFM_DROP = {"image", "streamable", "registered", "bootstrap"}

LASTFM_TOOL = {
    "type": "function",
    "function": {
        "name": "lastfm",
        "description": (
            "His Last.fm account — what he has actually listened to, and what "
            "Last.fm knows about the music. player scrobbles every play into "
            "this account, so `recent` is what he has been playing (including "
            "right now), `top_artists` / `top_tracks` / `top_albums` are his "
            "real charts over a period and `loved` is what he has hearted. "
            "Use it with music_library, not instead of it: that one is what he "
            "OWNS, this is what he PLAYS.\n"
            "The rest is the public catalogue — `similar_artists`, "
            "`similar_tracks`, `artist_info`, `tag_top_artists` — which is how "
            "you find him something new rather than guessing. Cross-check a "
            "recommendation against music_library to see whether he already "
            "has it.\n"
            "`love` and `unlove` are the only writes, and they are the same "
            "gesture as the heart in the player. There is no way to scrobble "
            "from here on purpose: his listening history is a record, not "
            "something to write into."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": sorted(LASTFM_ACTIONS),
                       "description": "What to ask for. Default `recent`."},
            "artist": {"type": "string",
                       "description": "The artist, for anything artist- or track-shaped."},
            "track": {"type": "string", "description": "The track title."},
            "album": {"type": "string", "description": "The album title."},
            "tag": {"type": "string",
                    "description": "A Last.fm tag (genre or mood), e.g. 'shoegaze'."},
            "user": {"type": "string",
                     "description": ("Another Last.fm user to ask about. Omit for "
                                     "him, which is what you almost always want.")},
            "period": {"type": "string", "enum": LASTFM_PERIODS,
                       "description": "For the top_* charts. Default `overall`."},
            "limit": {"type": "integer",
                      "description": "Rows to return (max 50). Default 20."},
            "page": {"type": "integer", "description": "1-based page, to read further."}},
            "required": []}},
}
LASTFM_TOOL_NAMES = {"lastfm"}

#: MODELS ARE THE DAEMON'S JOB, not the shell's [his, 2026-08-23]. Asked to
#: install a model, chatter reached for `run_bash` and `ollama pull` — and died
#: on the runner's address-space cap before the download started, then guessed
#: at macOS advice for a NixOS box. Both halves were avoidable: the cap is fixed
#: in tools/sandbox-exec.py, and a pull was never a shell job in the first
#: place. ollama's own HTTP API does it, chatter is already that daemon's
#: client, and the API streams progress — so the download is watched rather than
#: waited on, and it is the SAME endpoint whichever machine the window is on
#: (book's `$OLLAMA` is the tunnel to top).
MODEL_TOOL = {
    "type": "function",
    "function": {
        "name": "manage_models",
        "description": (
            "Look after the ollama models on his machine: `list` what is "
            "installed with sizes, `show` one model's real context length and "
            "capabilities, `pull` a new one from the ollama library (this can "
            "take many minutes for a 20 GB model — he sees the progress, so "
            "call it once and wait), and `remove` one to get the disk back. "
            "Use this rather than run_bash: `ollama` on the command line is a "
            "client for the same daemon, and here you get progress and a real "
            "error instead of a shell's. Pull only what he asked for by name — "
            "a wrong model is tens of gigabytes of his disk."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["list", "show", "pull", "remove"],
                       "description": "What to do. Default `list`."},
            "model": {"type": "string",
                      "description": ("The model, exactly as ollama names it "
                                      "(e.g. 'qwen3.6:27b'). Required for show, "
                                      "pull and remove.")},
            "confirm": {"type": "boolean",
                        "description": ("Required for `remove`: it deletes his "
                                        "weights and cannot be undone.")}},
            "required": ["action"]}},
}
MODEL_TOOL_NAMES = {"manage_models"}

#: A pull is minutes, not seconds, so it gets its own long leash — and the disk
#: is checked before one starts, because the models live on `/` and it runs
#: fairly full (root AGENTS.md).
MODEL_PULL_MS = 90 * 60 * 1000
MODEL_DISK_FLOOR = 5 * 1024 * 1024 * 1024

#: The library and the queue socket both live with the player, on `top`.
MUSIC_SCRIPT = "/home/lam/nix/apps/player/tools/library-ipc.py"

#: Which player, and what drives it. `playerctl` is the client (a real MPRIS
#: implementation — QtDBus was the obvious route and is a dead end: PySide
#: cannot demarshal MPRIS's `a{sv}` Metadata, so the title came back empty,
#: measured against the real player 2026-08-23). Both are overridable, which is
#: how the harness drives a STUB and never his player — he is listening on it
#: while the tests run (root AGENTS.md).
#: WHICH player, when he does not say. `player,%any` is playerctl's own
#: fallback list: his own app if it is on the bus, otherwise whatever else is
#: — a browser tab, mpv, anything that speaks MPRIS. It used to be `player`
#: alone, which meant the tool could not touch the thing actually making noise
#: [his, 2026-08-23: *"i want it to be able to control all types of media
#: playback"*].
MPRIS_NAME = os.environ.get("ORACLE_MPRIS", "player,%any")

#: The MIXER. His player does not expose an MPRIS volume — it answers 1.0 for
#: ever — so "what is the volume" and "turn it down" were both lies through
#: playerctl [his, 2026-08-23: *"right now it thinks the volume level is always
#: 100 since player doesnt expose any volume its always 100 so it should be
#: reading the system volume level"*]. This machine is PipeWire, so `wpctl` is
#: the true answer for both reading and setting.
WPCTL = os.environ.get("ORACLE_WPCTL", "wpctl")
AUDIO_SINK = os.environ.get("ORACLE_AUDIO_SINK", "@DEFAULT_AUDIO_SINK@")
PLAYERCTL = os.environ.get("ORACLE_PLAYERCTL", "playerctl")

#: The PAGE-READER tool. web_search returns Tavily's snippets, which are a
#: paragraph at most — so a model handed a link (by him, or by its own search)
#: could not actually READ it. This closes that: one URL in, the page's text
#: out, paged. It is the only tool that fetches arbitrary web TEXT (fetch_image
#: fetches bytes and shows them; search_images finds URLs), and it reaches
#: nothing but http(s) — no file://, no local scheme.
FETCH_URL_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": (
            "Fetch one web page or text/JSON URL and read its contents. Use it "
            "whenever you have a link and need what is actually on the page — "
            "after web_search when a snippet is not enough, or when he gives "
            "you a URL. HTML is reduced to readable text. Long pages come back "
            "truncated: read again with `offset` set to the `next_offset` you "
            "were given to continue. http and https only, and it cannot post a "
            "form or log in."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string",
                    "description": "Absolute http(s) URL of the page to read."},
            "offset": {"type": "integer",
                       "description": ("0-based character offset into the page "
                                       "text. Default 0; use next_offset to page.")}},
            "required": ["url"]}},
}
FETCH_URL_TOOL_NAMES = {"fetch_url"}
#: Caps: the biggest body worth downloading, and how much page TEXT one call
#: hands back (his rule 5 — a tool result must never blow the context window).
FETCH_URL_MAX_BYTES = 4 * 1024 * 1024
FETCH_URL_CHARS = 20000


#: ---- call_api: a JSON web API as a tool ------------------------------------
#: `fetch_url` already GETs a JSON endpoint, but it hands the model the RAW
#: body against a 20k character cap — a Danbooru `posts.json` spends that whole
#: budget on ~8 posts of metadata nobody asked for, and it can send no
#: credentials at all. This tool is the same GET with the three things that
#: were missing: a KEYRING (so a key never enters the transcript), FIELD
#: PROJECTION applied before the cap (20 rows of id/file_url/tags instead of 8
#: whole posts), and a small REGISTRY of sites whose endpoint shape the model
#: would otherwise have to guess. Read-only by construction (his call): GET and
#: HEAD only, so a tool-calling model holding his keys cannot favourite, upload
#: or delete anything on a remote account.
#:
#: The registry is a convenience, not the surface — `url` reaches any http(s)
#: JSON API, with `auth` naming a keyring entry for its headers.
API_SITES = {
    "danbooru": {
        "base": "https://danbooru.donmai.us", "path": "/posts.json",
        "params": {"limit": 20},
        "fields": ["id", "file_url", "preview_file_url", "tag_string",
                   "rating", "score", "source"],
        "note": "tags= is space-separated; 2 tags max without an account",
    },
    "safebooru": {
        "base": "https://safebooru.donmai.us", "path": "/posts.json",
        "params": {"limit": 20},
        "fields": ["id", "file_url", "preview_file_url", "tag_string",
                   "rating", "score", "source"],
        "note": "danbooru's safe-rating mirror, same API",
    },
    "e621": {
        "base": "https://e621.net", "path": "/posts.json",
        "params": {"limit": 20}, "select": "posts",
        "fields": ["id", "file.url", "preview.url", "tags.general", "rating",
                   "score.total", "sources"],
        "auth": {"basic": ["username", "api_key"]},
        "note": ("tags= is space-separated; answers anonymous requests with "
                 "403, so it needs a keyring entry"),
    },
    "gelbooru": {
        "base": "https://gelbooru.com", "path": "/index.php",
        "params": {"page": "dapi", "s": "post", "q": "index", "json": "1",
                   "limit": 20},
        "select": "post",
        "fields": ["id", "file_url", "preview_url", "tags", "rating", "score",
                   "source"],
        "auth": {"params": ["api_key", "user_id"]},
        "note": ("tags= is space-separated; answers anonymous requests with "
                 "401, so it needs a keyring entry"),
    },
    "rule34": {
        "base": "https://api.rule34.xxx", "path": "/index.php",
        "params": {"page": "dapi", "s": "post", "q": "index", "json": "1",
                   "limit": 20},
        "fields": ["id", "file_url", "preview_url", "tags", "rating", "score",
                   "source"],
        "auth": {"params": ["api_key", "user_id"]},
        "note": ("tags= is space-separated; answers anonymous requests with a "
                 "\"missing authentication\" body, so it needs a keyring entry"),
    },
    "yandere": {
        "base": "https://yande.re", "path": "/post.json",
        "params": {"limit": 20},
        "fields": ["id", "file_url", "preview_url", "tags", "rating", "score",
                   "source"],
        "note": "moebooru; tags= is space-separated, no key needed",
    },
    "konachan": {
        "base": "https://konachan.com", "path": "/post.json",
        "params": {"limit": 20},
        "fields": ["id", "file_url", "preview_url", "tags", "rating", "score",
                   "source"],
        "note": "moebooru; tags= is space-separated, no key needed",
    },
}
#: The client identity every call carries unless its site names its own. NOT
#: fetch_url's browser UA: danbooru 403s that string and 200s this one, and
#: e621's terms ask for a named client outright.
API_USER_AGENT = b"chatter/1.0 (oracle desktop client)"
#: Caps, his rule 5: a tool result must never blow the context window.
API_MAX_BYTES = 4 * 1024 * 1024
API_CHARS = 16000
API_MAX_ROWS = 100
#: Query parameters whose VALUE is a credential. Stripped from every URL that
#: reaches the model, the transcript or the disclosure line — the point of the
#: keyring is that a key is never written down where a session file can keep it.
API_SECRET_PARAMS = {"api_key", "apikey", "key", "login", "user_id", "username",
                     "password", "token", "access_token", "pw"}
#: The keyring: `~/.config/oracle/api-keys.json` (override $ORACLE_API_KEYS), a
#: dict of entry-name -> {"params": {...}, "headers": {...}, "basic": [u, p]}.
#: Read on every call, so adding a key needs no restart. Absent file -> {}.
API_KEYS_PATH = os.path.expanduser(
    os.environ.get("ORACLE_API_KEYS", "~/.config/oracle/api-keys.json"))


def api_credentials(name):
    """The keyring entry for `name`, or {} — never raises, never logged."""
    try:
        with open(API_KEYS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        entry = data.get(name)
        return entry if isinstance(entry, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _api_sites_blurb():
    """The registry as one line per site, built from the table so the tool
    description cannot drift from what the code actually sends."""
    return "\n".join(
        "  " + k + " — " + v["base"] + v["path"] + "; " + v.get("note", "")
        + (" (a key is configured)" if v.get("auth") and api_credentials(k)
           else "")
        for k, v in sorted(API_SITES.items()))


CALL_API_TOOL = {
    "type": "function",
    "function": {
        "name": "call_api",
        "description": (
            "Query a JSON web API and get back only the fields you asked for. "
            "Use this instead of fetch_url whenever the target is an API "
            "rather than a page: it parses the JSON, pulls out the list of "
            "results and projects each row down to the fields you name, so a "
            "search returns twenty usable rows instead of eight posts of "
            "metadata. Read-only — GET and HEAD only, it cannot post, upload "
            "or delete.\n"
            "Name a `site` for one of the image boards below and you need only "
            "give `params` (their search parameter is `tags`, space-separated, "
            "e.g. {\"tags\": \"cat_girl rating:general\", \"limit\": 10}); the "
            "endpoint, the result list and a sensible default field set are "
            "already known — and a row's `file_url` goes straight to "
            "fetch_image when he wants to SEE one. For anything else give an "
            "absolute `url` and, if "
            "it needs credentials, the name of a keyring entry in `auth`. "
            "Known sites:\n" + _api_sites_blurb()),
        "parameters": {"type": "object", "properties": {
            "site": {"type": "string", "enum": sorted(API_SITES),
                     "description": "One of the known sites. Omit and give `url` for any other API."},
            "url": {"type": "string",
                    "description": ("Absolute http(s) URL of the endpoint, for an API "
                                    "that is not in the site list. Ignored when `site` is given.")},
            "path": {"type": "string",
                     "description": "Override the site's default endpoint path (e.g. /tags.json)."},
            "params": {"type": "object",
                       "description": ("Query parameters as a flat object, e.g. "
                                       "{\"tags\": \"fox rating:general\", \"limit\": 10}.")},
            "fields": {"type": "array", "items": {"type": "string"},
                       "description": ("Fields to keep from each result row; dotted paths "
                                       "reach into nested objects (\"file.url\"). Omit for the "
                                       "site's defaults, or pass [\"*\"] to keep whole rows.")},
            "select": {"type": "string",
                       "description": ("Dotted path to the list inside the response, when the "
                                       "API wraps it (e.g. \"posts\"). Omit when the response "
                                       "is a bare array or the site is known.")},
            "auth": {"type": "string",
                     "description": ("Name of a keyring entry whose headers/params to send. "
                                     "Only for `url` calls; a known site uses its own entry.")},
            "offset": {"type": "integer",
                       "description": "0-based row offset into the result list; use next_offset to page."},
            "method": {"type": "string", "enum": ["GET", "HEAD"],
                       "description": "Default GET."}},
            "required": []}},
}
CALL_API_TOOL_NAMES = {"call_api"}


def _api_dig(obj, path):
    """`obj` walked by a dotted path; None if any step is missing. List indices
    may appear as a numeric step ("sources.0")."""
    cur = obj
    for part in str(path).split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def _api_safe_url(url):
    """`url` with every credential parameter's value replaced by a marker, so a
    key cannot reach the model, the transcript or the disclosure line."""
    u = QUrl(url)
    q = QUrlQuery(u)
    items = q.queryItems()
    if not any(k.lower() in API_SECRET_PARAMS for k, _ in items):
        return url
    out = QUrlQuery()
    for k, v in items:
        out.addQueryItem(k, "(set)" if k.lower() in API_SECRET_PARAMS else v)
    u.setQuery(out)
    return u.toString()


class _PageText(HTMLParser):
    """HTML -> readable text, stdlib only. Drops script/style/head noise, turns
    block elements into line breaks and collapses runs of whitespace, and keeps
    the <title>. Not a renderer — enough that a model reads prose instead of
    markup, which is all the tool promises."""

    # Chrome, not content: a page's nav/menu/form furniture would otherwise be
    # the first several thousand characters the model reads (Wikipedia's is
    # ~2k before the article starts) and it is never what was asked for.
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe",
            "nav", "aside", "form", "select", "button", "menu"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "header", "footer", "blockquote", "pre",
             "ul", "ol", "table", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data.strip()
            return
        if data.strip():
            self.parts.append(re.sub(r"[ \t\r\f\v]+", " ", data))

    def text(self):
        out = "".join(self.parts)
        out = re.sub(r"[ \t]*\n[ \t]*", "\n", out)
        return re.sub(r"\n{3,}", "\n\n", out).strip()

#: Where fetched images land — LOCAL to the machine running the window (not top,
#: unlike the sandbox/sessions/memory), because a QML Image loads a local file
#: and the download is an in-process web GET that needs no ssh. Override with
#: $ORACLE_IMAGES.
IMAGES_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_IMAGES", "~/.local/share/oracle/images"))

#: Where a GENERATED picture lands (make_image). Under the image store, because
#: it is the same kind of thing: a file this chat produced, kept so a reloaded
#: session still shows it.
MAKE_IMAGE_DIR = os.path.join(IMAGES_ROOT, "made")

#: A ceiling on a single image download, so a mis-pointed URL cannot pull a
#: multi-gigabyte body into memory.
IMAGE_MAX_BYTES = 20 * 1024 * 1024

#: Attachments dragged onto the window and inlined into the outgoing message as
#: context. Read LOCALLY where the window runs (they are the user's own dropped
#: files, not sandbox paths), text only, capped so a big file cannot blow the
#: model's context: per-file and whole-turn byte ceilings, respecting his
#: context-budget rule. A binary or over-cap file is NAMED, not inlined.
ATTACH_FILE_MAX = 128 * 1024        # per attachment, bytes of text inlined
ATTACH_TOTAL_MAX = 512 * 1024       # all attachments in one turn, bytes
ATTACH_IMAGE_MAX = 8 * 1024 * 1024  # per dropped image, bytes sent to a vision model

#: Beyond inlining a dropped file's text, oracle also STAGES each non-image
#: attachment into the file-tool sandbox (ATTACH_STAGE_DIR under SANDBOX_ROOT on
#: top), so the model can read the FULL file (the inline text is capped) and
#: read/edit/write it through the same file tools. Capped to the sandbox's own
#: WRITE_MAX_BYTES (2 MB) so a copy over the ssh master stays quick and cannot
#: outrun what the tools would accept back.
ATTACH_STAGE_MAX = 2_000_000        # per file copied into the sandbox for the tools
ATTACH_STAGE_DIR = "attachments"    # sandbox subdir dropped files are staged under

#: content-type → file extension for a saved image (cosmetic — QML's Image sniffs
#: the bytes — but tidy). Anything else falls back to the URL's suffix, then .img.
IMAGE_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
             "image/webp": ".webp", "image/bmp": ".bmp", "image/svg+xml": ".svg",
             "image/tiff": ".tiff", "image/x-icon": ".ico", "image/avif": ".avif"}

#: HOW A WATCH PAGE BECOMES A STREAM (show_video). yt-dlp is the thing that knows
#: — it is already installed on both hosts (home/pkgs/media/aquire.nix) and
#: oracle's wrapper puts it on PATH. `-f b` asks for the best SINGLE file: never
#: a separate video+audio pair, which would have to be downloaded and merged
#: before anything could play, and `-S res:1080` keeps a 4K variant off a bubble
#: 500px wide.
#:
#: THE LADDER, and why it exists [his, 2026-08-23: *"look into why it cant play
#: the streams of the steve reich and phillip glass videos"*]. YouTube hands
#: yt-dlp a URL that then **403s to every player on this machine** — measured on
#: three watch pages that afternoon: yt-dlp's OWN downloader, ffmpeg and mpv all
#: got 403 on the progressive mp4, so nothing chatter could have done with that
#: URL would have played. What changes the answer is WHICH CLIENT the extraction
#: pretends to be. Same three videos, same minute:
#:
#:     default / mweb / android_vr / web_embedded  ->  itag 18, HTTP 403
#:     web / web_safari / ios                      ->  "requested format is not available"
#:     tv                                          ->  "the page needs to be reloaded"
#:     tv_simply                                   ->  itag 18, HTTP 206, plays
#:
#: So rung 1 asks the default way and PREFERS HLS (`b[protocol^=m3u8]/b`) — a
#: manifest is the highest quality single stream YouTube offers, up to 1080p,
#: and needs no headers — and rung 2 falls back to `tv_simply`, which is 360p
#: but answered for every video that had failed. Each rung's stream is PROVED
#: with a ranged GET before a card is drawn (`_video_probe`), so a dead URL
#: costs a retry rather than a card that fails when he presses play.
#:
#: Override the binary with $ORACLE_YTDLP (the harness does, with a stub, so it
#: never touches the network).
VIDEO_RESOLVER = os.environ.get("ORACLE_YTDLP", "yt-dlp")
VIDEO_RESOLVE_BASE = ["-j", "--no-playlist", "--no-warnings", "-S", "res:1080"]
VIDEO_RESOLVE_LADDER = [
    ["-f", "b[protocol^=m3u8]/b"],
    ["--extractor-args", "youtube:player_client=tv_simply", "-f", "b"],
]
VIDEO_RESOLVE_MS = 45000            # a resolver that hangs is a failed resolve

#: A URL that plainly names a media file skips the resolver: it is HEADed, and
#: if the server says it is video then it IS the stream. Anything the server
#: does not confirm falls through to yt-dlp — a page can wear a media-looking
#: URL, and handing QML a stream that turns out to be HTML fails silently in the
#: decoder, which is the one thing docs/DESIGN.md §10 forbids.
VIDEO_DIRECT_RE = re.compile(r"\.(mp4|m4v|webm|mkv|mov|ogv|m3u8)(?:$|[?#])", re.I)
VIDEO_CTYPES = ("video/", "application/vnd.apple.mpegurl", "application/x-mpegurl",
                "audio/mpegurl", "application/octet-stream")

#: The WRITE root — **`/` since 2026-08-22, his call**: "i dont really want
#: them to be [sandboxed]". Until then write_file/edit_file/move_path/
#: delete_path/make_dir resolved against SANDBOX_ROOT while the read ops
#: already reached the whole filesystem, so a chatter agent could read any file
#: on the machine and then not fix it — the one half-jail left, and what made
#: it an assistant rather than an agent. It is a real security decision and it
#: is his: a local model can now overwrite and delete anything the user can,
#: with no confirmation step. `ORACLE_WRITE_ROOT` puts the jail back — point it
#: at SANDBOX_ROOT for the pre-2026-08-22 behaviour, or at his home for
#: something in between. SANDBOX_ROOT survives as the model's SCRATCH directory
#: (attachment staging, run_python's working directory), which is what it
#: always usefully was.
WRITE_ROOT = os.path.expanduser(os.environ.get("ORACLE_WRITE_ROOT", "/"))
#: True when writes are unjailed, i.e. the write root is the whole filesystem.
#: The write tools' own descriptions are built from this, so what the model is
#: told about its reach is never a stale string (docs/DESIGN.md §10).
WRITE_FREE = os.path.realpath(WRITE_ROOT) == os.sep
#: How the write tools describe a path they take, and their reach — one phrase
#: each, so re-jailing with ORACLE_WRITE_ROOT re-words the tools rather than
#: leaving them lying about a sandbox that is no longer there.
WRITE_PATH = ("absolute (or relative to '/')" if WRITE_FREE
              else "relative to your sandbox root")
WRITE_WHERE = ("anywhere on the filesystem" if WRITE_FREE else "in your sandbox")

#: The FILE TOOLS oracle offers the model on EVERY turn (no toggle — his call:
#: "always available to the model"). Reading and manipulation both, and every
#: one runs THROUGH tools/sandbox-fs.py against a root it cannot escape (see FS
#: below and apps/oracle/AGENTS.md) — but since 2026-08-22 BOTH roots are `/`
#: by default, so the containment is a mechanism kept for the env overrides,
#: not a jail the model is in. The READ-ONLY tools (list_dir/read_file/
#: find_files/search_text/show_tree) reach EITHER machine — they take an
#: optional `host` ("top"/"book") so the model can read book's files from a top
#: window and top's from a book window, not just whichever machine its own
#: compute happens to run on. The MUTATING tools (write/edit/move/delete/
#: make_dir) always land on `top` and take no `host`. Every path is
#: root-relative, and reads are paginated so the model asks for more rather
#: than assuming a short read is the whole file.
FILE_TOOLS = [
    {"type": "function", "function": {
        "name": "list_dir",
        "description": ("List a directory anywhere on the filesystem (top or "
                        "book). Paths are relative to the filesystem root '/'; "
                        "'.' is '/'. Read-only. Long listings are truncated."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "Directory to list, relative to '/'. Default '.'."},
            "host": {"type": "string", "enum": ["top", "book"],
                     "description": "Which machine to read. Default 'top'."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": ("Read a text file from anywhere on the filesystem (top or "
                        "book; paths relative to '/'; read-only). Returns at most "
                        "a few hundred lines; if `truncated` is true read again "
                        "with `offset` set to `next_offset` to page through the "
                        "rest."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "File to read, relative to '/'."},
            "offset": {"type": "integer",
                       "description": "0-based line to start at. Default 0."},
            "limit": {"type": "integer",
                      "description": "Max lines to return this call."},
            "host": {"type": "string", "enum": ["top", "book"],
                     "description": "Which machine to read. Default 'top'."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": ("Create or overwrite a text file " + WRITE_WHERE + " with "
                        "the given content. Parent directories are created."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File to write, " + WRITE_PATH + "."},
            "content": {"type": "string", "description": "Full new file contents."}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": ("Replace an exact substring in a file " + WRITE_WHERE + ". "
                        "`old` must match once unless `replace_all` is set. Use "
                        "write_file to create a file or replace it wholesale."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "File to edit, " + WRITE_PATH + "."},
            "old": {"type": "string", "description": "Exact text to find."},
            "new": {"type": "string", "description": "Text to put in its place."},
            "replace_all": {"type": "boolean",
                            "description": "Replace every match, not just a unique one."}},
            "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {
        "name": "move_path",
        "description": "Move or rename a file or directory " + WRITE_WHERE + ".",
        "parameters": {"type": "object", "properties": {
            "src": {"type": "string", "description": "Path to move, " + WRITE_PATH + "."},
            "dst": {"type": "string", "description": "Destination, " + WRITE_PATH + "."}},
            "required": ["src", "dst"]}}},
    {"type": "function", "function": {
        "name": "delete_path",
        "description": ("Delete a file or directory " + WRITE_WHERE + ". Pass "
                        "`recursive` to delete a non-empty directory. This is "
                        "permanent — there is no trash and no undo, so be sure "
                        "before you delete something you did not create."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path to delete, " + WRITE_PATH + "."},
            "recursive": {"type": "boolean",
                          "description": "Delete a directory and its contents."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "make_dir",
        "description": "Create a directory (and parents) " + WRITE_WHERE + ".",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory to create, " + WRITE_PATH + "."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "find_files",
        "description": ("Find files and directories anywhere on the filesystem "
                        "(top or book) by shell glob pattern (paths relative to "
                        "'/'; read-only). Use '**' to match across subdirectories "
                        "(e.g. '**/*.py'). Returns matching paths; long result "
                        "lists are truncated."),
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string",
                        "description": "Glob, e.g. '*.md' or '**/*.py'."},
            "path": {"type": "string",
                     "description": "Directory to search under, relative to '/'. Default '.'."},
            "host": {"type": "string", "enum": ["top", "book"],
                     "description": "Which machine to search. Default 'top'."}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "search_text",
        "description": ("Search file contents anywhere on the filesystem (top or "
                        "book) for a regular expression (like grep; paths relative "
                        "to '/', read-only). Returns matching lines with their "
                        "file and line number. Binary files are skipped and long "
                        "result sets are truncated."),
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Regular expression to search for."},
            "path": {"type": "string",
                     "description": "File or directory to search, relative to '/'. Default '.'."},
            "glob": {"type": "string",
                     "description": "Only search files whose name matches this glob, e.g. '*.py'."},
            "ignore_case": {"type": "boolean",
                            "description": "Case-insensitive match."},
            "host": {"type": "string", "enum": ["top", "book"],
                     "description": "Which machine to search. Default 'top'."}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "show_tree",
        "description": ("Show the directory structure under a path anywhere on "
                        "the filesystem (top or book) as an indented tree (paths "
                        "relative to '/'; read-only). Depth- and entry-limited."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "Directory to show, relative to '/'. Default '.'."},
            "depth": {"type": "integer",
                      "description": "How many levels deep to descend. Default 5."},
            "host": {"type": "string", "enum": ["top", "book"],
                     "description": "Which machine to show. Default 'top'."}},
            "required": []}}},
]

#: The CURRENT-TIME tool, offered on every turn beside the file and web tools.
#: Without it the model answers "now" from its training and gets timezone/DST
#: conversions wrong (it put Juneau an hour out — the classic AKDT/AKST slip).
#: This resolves any IANA zone through Python's zoneinfo, which carries the real
#: DST rules, so the model never has to compute an offset itself. Handled
#: locally in `Ollama` (no subprocess — a wall-clock instant is host-neutral).
TIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": (
            "Get the current date and time. Pass an IANA timezone name to get "
            "the time there (correct for daylight saving); omit it for UTC. "
            "Always use this instead of computing a timezone offset yourself."),
        "parameters": {"type": "object", "properties": {
            "timezone": {"type": "string",
                         "description": ("IANA timezone, e.g. 'America/Juneau' "
                                         "or 'Europe/London'. Omit for UTC.")}},
            "required": []}},
}

#: The SELF-DESCRIPTION tool, offered every turn beside the time tool. Without
#: it a model answers "which model are you?" from whatever its training baked in
#: — usually a different model's name — and "what machine are you on?" with a
#: guess. This resolves both from the live process: the model id ollama is
#: actually serving this turn with (`self._model`), and the host/OS/arch/cores/
#: RAM read off the machine the window runs on (book or top). Handled locally in
#: `Ollama` (no subprocess — it is all in-process facts and is host-neutral).
SELF_TOOL = {
    "type": "function",
    "function": {
        "name": "describe_self",
        "description": (
            "Look up who and what you actually are right now — everything about "
            "yourself you can access. The exact model id you are served as this "
            "turn and your provider/backend; the app and the machine you run on "
            "(hostname, OS, CPU architecture, cores, memory); your context "
            "window ceiling and how much of it is currently filled; your last "
            "generation speed in tokens/sec; your active persona / base system "
            "prompt; the durable memories you have saved; the tools available to "
            "you this turn; your sampling options; and this conversation's size. "
            "Use this instead of guessing any of it from your training."),
        "parameters": {"type": "object", "properties": {}, "required": []}},
}

#: tool name -> the `op` tools/sandbox-fs.py dispatches on.
FILE_TOOLS.append({"type": "function", "function": {
    "name": "file_metadata",
    "description": (
        "What a file IS, without reading it: its size, when it last changed, "
        "its REAL type (sniffed from the bytes, not guessed from the "
        "extension), the line and word count of a text file, and — for audio, "
        "video and images — the container, duration, bitrate, codecs, "
        "dimensions and embedded TAGS (artist, album, title, track number, "
        "camera, and whatever else is in the file). Use it whenever the "
        "question is about the file rather than its contents: how long is this "
        "track, who is it by, what is this video encoded with, how big is it, "
        "is this really a PNG. Read-only, works on either machine, and far "
        "cheaper than read_file on a large or binary file — read_file on a "
        "flac tells you nothing at all."),
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string",
                 "description": "The file (or directory) to inspect, relative to '/'."},
        "hash": {"type": "boolean",
                 "description": ("Also compute the file's sha256. Off by "
                                 "default: it reads every byte.")},
        "host": {"type": "string", "enum": ["top", "book"],
                 "description": "Which machine the file is on. Default 'top'."}},
        "required": ["path"]}}})

FILE_OP = {"list_dir": "list", "read_file": "read", "write_file": "write",
           "edit_file": "edit", "move_path": "move", "delete_path": "delete",
           "make_dir": "mkdir", "find_files": "glob", "search_text": "grep",
           "show_tree": "tree", "file_metadata": "meta"}
FILE_TOOL_NAMES = set(FILE_OP)

#: The house rules of a directory tree, by filename. `~/nix` and every tree
#: under it carries an `AGENTS.md` (the nearest one wins, and `CLAUDE.md` is its
#: symlink at the repo root) stating how work is done there — the rebuild
#: command, the commit rules, the things never to touch. A model that has not
#: read it will cheerfully hand-edit a generated file or leave a change
#: unrebuilt, and he should not have to say so on every request [his,
#: 2026-08-22: *"i just want it to be easy for me to change things about chatter
#: and the rest of the system without needing to point it to every little
#: thing"*].
HOUSE_FILES = ("AGENTS.md", "CLAUDE.md")

#: NAMED, never inlined. `~/nix/AGENTS.md` alone is 62 KB — a fifth of the
#: 32k-token window — and there are three more of them in the trees oracle
#: touches most. The pointer costs a line; reading it is the model's own call,
#: with its own read_file, only when it is actually working in that tree.

#: The READ-ONLY tool names — these five (and only these) accept a `host`
#: argument, since only they resolve against the whole-filesystem READ_ROOT
#: rather than the single sandbox on top (see `Ollama._fs_argv`).
FILE_READ_TOOL_NAMES = {"list_dir", "read_file", "find_files", "search_text",
                        "show_tree", "file_metadata"}

#: The SESSION-READ tools (list_sessions / read_session), offered beside the
#: file and web tools so the model can reach past conversations he has had with
#: it — not just this one. Read-only from the model's side: no save/delete
#: tool is offered, so a model call can never touch what saveCurrent() writes.
#: Backed by the same tools/sessions-store.py the session picker uses (list/load
#: ops), which already validates the id as a bare filename — no new jail needed.
SESSION_TOOLS = [
    {"type": "function", "function": {
        "name": "list_sessions",
        "description": ("List his previous conversation sessions with you (not "
                        "this one): id, title, when each was last updated, and "
                        "how many turns it has. Use read_session with an id from "
                        "this list to read one."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "read_session",
        "description": ("Read the full transcript of one previous conversation "
                        "session by id (see list_sessions)."),
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "Session id, from list_sessions."}},
            "required": ["id"]}}},
]
SESSION_TOOL_NAMES = {"list_sessions", "read_session"}

#: oracle's OWN durable memories — distinct from the read-only session tools
#: above. A session is a past transcript it can READ; a memory is a fact it
#: deliberately WROTE and keeps across conversations (the board / Claude-memory
#: pattern: one fact per entry with a shared index). These three tools let the
#: model create, revise and forget its memories itself; the current set is also
#: injected into every turn's system prompt (see `_system_prompt`) so it recalls
#: them without having to call a tool first. Backed by tools/memory-store.py.
MEMORY_TOOLS = [
    {"type": "function", "function": {
        "name": "save_memory",
        "description": ("Save a durable fact you want to remember across all "
                        "future conversations, or UPDATE one you already saved. "
                        "Use this for lasting things about him (his name, his "
                        "preferences, ongoing projects, decisions) — not for "
                        "one-off details of the current chat. Omit id to create a "
                        "new memory; pass the id of an existing memory to replace "
                        "its text. Your current memories are listed for you in "
                        "your context each turn."),
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "The fact to remember, one "
                     "self-contained sentence or two."},
            "id": {"type": "string", "description": "Optional: the id of an "
                   "existing memory to update (from your memory list). Omit to "
                   "create a new one."}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "list_memories",
        "description": ("List every durable memory you have saved (id, text, when "
                        "created and last updated), newest first. Your memories "
                        "are already shown in your context, so you usually do not "
                        "need this — reach for it to get ids or double-check."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "delete_memory",
        "description": ("Delete a durable memory by id (from your memory list) "
                        "when it is wrong or no longer true."),
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "Memory id to delete."}},
            "required": ["id"]}}},
]
MEMORY_TOOL_NAMES = {"save_memory", "list_memories", "delete_memory"}

#: The CODE-RUNNER tool, offered every turn beside the file tools. It lets the
#: model actually RUN Python instead of only reasoning about it — the gap
#: gemma4:e4b named honestly ("no code-execution env"). Running model-written
#: code on `top` is a security decision he took deliberately (board, 2026-08-11);
#: tools/sandbox-exec.py is the jail it runs in — the sandbox dir as working
#: directory, NETWORK cut with an unprivileged namespace, and wall-time / CPU /
#: memory / output all capped. It is NOT a container: the code runs as the user
#: and can still read his files (as the read tools already allow) and, with an
#: absolute path, write outside the sandbox — the description says so plainly
#: (docs/DESIGN.md §10, honesty in both directions), and there is no toggle
#: (his call, like every other tool here).
EXEC_TOOL = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": (
            "Run a Python 3 program and get its stdout, stderr and exit code "
            "back — use this to actually compute, test or verify code instead "
            "of working the answer out in your head. It runs on the host as the "
            "user, with the network up and the whole filesystem reachable, so "
            "it can do real work — and real damage, so read before you "
            "overwrite and never delete what you did not create. The working "
            "directory is your scratch directory unless you name `cwd`, and a "
            "run is killed after a few seconds. Only the standard library is "
            "available. Print what you want to see; a bare expression is not "
            "echoed."),
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string",
                     "description": "The Python 3 source to run."},
            "cwd": {"type": "string",
                    "description": ("Optional working directory (absolute). "
                                    "Default: your scratch directory.")},
            "stdin": {"type": "string",
                      "description": "Optional text fed to the program's stdin."},
            "timeout": {"type": "integer",
                        "description": "Wall-clock seconds to allow (default 10, max 30)."}},
            "required": ["code"]}},
}
EXEC_TOOL_NAMES = {"run_python"}

#: The SHELL, offered every turn beside run_python — his call, 2026-08-22:
#: "add bash tooling to agents in chatter, not just python stuff. give them the
#: same abilities and tools you do when manipulating files". The file tools
#: already reach the whole filesystem, but the work an agent actually does to
#: files is shell work — `grep -rn`, `cp -a`, `git diff`, `find … -exec`, a
#: for-loop over a directory — and writing each of those as a Python program was
#: the one thing that still made this an assistant rather than an agent. It runs
#: through the SAME tools/sandbox-exec.py as run_python (`lang: "bash"`), so the
#: caps, the cwd rules and the disclosure are shared and cannot drift.
BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "run_bash",
        "description": (
            "Run a bash command (or a whole script) and get its stdout, stderr "
            "and exit code back — this is your shell, and the right tool for "
            "real file work: grep, find, sed, cp, mv, mkdir, diff, git, wc, "
            "head, tar, and pipelines of them. It runs on the host as the user, "
            "with the network up and the whole filesystem reachable, so it can "
            "do real work — and real damage: look before you overwrite, prefer "
            "a targeted edit to a wholesale replacement, and never delete or "
            "move anything you did not create unless he asked for it. There is "
            "no confirmation step and nothing is undone. `sudo` is not "
            "available. The working directory is your scratch directory unless "
            "you name `cwd`, and a command is killed after a few seconds, so "
            "keep it non-interactive and bounded — never start a server, an "
            "editor or anything that waits for input."),
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string",
                        "description": "The bash to run. Multiple lines are fine."},
            "cwd": {"type": "string",
                    "description": ("Optional working directory (absolute). "
                                    "Default: your scratch directory.")},
            "stdin": {"type": "string",
                      "description": "Optional text fed to the command's stdin."},
            "timeout": {"type": "integer",
                        "description": "Wall-clock seconds to allow (default 10, max 30)."}},
            "required": ["command"]}},
}
BASH_TOOL_NAMES = {"run_bash"}

#: SKILLS — the reusable expert instructions Claude Code carries, reached here
#: as a REAL TOOL rather than baked in as a persona (his call, 2026-08-22: the
#: video-prompt skill used to be the `vidprompt` base prompt, which meant
#: switching persona for one message and switching back afterwards, and only
#: ever covered the one skill). A skill is a directory under the skills root
#: (`~/.local/share/oracle/skills`, ORACLE_SKILLS): `SKILL.md` (YAML
#: frontmatter with `name`/`description`, then the
#: instructions) plus optional reference guides beside it. Nothing is vendored
#: and nothing lands in this public repo — the runtime dir is machine-local,
#: existing on each host chatter runs on. Read in-process off the host the
#: window runs on: it is a plain file read, so unlike the sandbox/session/
#: memory stores it needs no ssh branch to `top`.
SKILLS_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_SKILLS", "~/.local/share/oracle/skills"))
#: One skill file's text, capped so a huge guide cannot swallow the context
#: (the largest today, video-prompt's full-reference guide, is ~24k).
SKILL_MAX_CHARS = 40000
SKILL_TOOL_NAMES = {"use_skill"}


def skill_dirs():
    """Every readable skill directory, sorted by name. Absent root -> []."""
    try:
        return sorted((d for d in Path(SKILLS_ROOT).iterdir()
                       if (d / "SKILL.md").is_file()), key=lambda d: d.name)
    except OSError:
        return []


def _skill_read(path):
    """One skill file as `(text, truncated)`, capped at SKILL_MAX_CHARS."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > SKILL_MAX_CHARS:
        return (text[:SKILL_MAX_CHARS], True)
    return (text, False)


def _skill_front(text):
    """`(description, body)` from a SKILL.md — the `description:` out of the
    leading `---` frontmatter and the instructions with that block stripped.
    `_front_matter` (below, shared with the agent definitions) does the
    parsing; no YAML parser, the shape is fixed and stdlib-only is the rule for
    everything chatter reads."""
    fields, body = _front_matter(text)
    return (fields.get("description", "").strip(), body)


def skill_catalog():
    """`[{name, description}]` for every installed skill — what the system
    prompt lists and what the tool's own `name` enum is built from."""
    out = []
    for d in skill_dirs():
        try:
            text, _ = _skill_read(d / "SKILL.md")
        except OSError:
            continue
        desc, _body = _skill_front(text)
        out.append({"name": d.name, "description": desc})
    return out


def skill_tool(catalog=None):
    """The `use_skill` function tool, built from the skills actually present —
    the name enum and the description name them, so the model cannot call a
    skill that is not installed. `None` when there are none, and the tool is
    then not offered at all (docs/DESIGN.md §10 — never an affordance that is
    not there)."""
    cat = skill_catalog() if catalog is None else catalog
    if not cat:
        return None
    listing = "; ".join("%s: %s" % (s["name"], s["description"]) for s in cat)
    return {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": (
                "Load a SKILL — a set of expert instructions for one specific "
                "job, written for exactly this task and better than anything "
                "you would improvise. Call it BEFORE you start writing "
                "whenever the job matches one, then follow what it returns to "
                "the letter, including its output contract (a skill may "
                "require that your whole reply IS the thing it produces, with "
                "no preamble and no offer to revise). Call it again with "
                "`guide` to read one of the reference guides it lists. "
                "Installed skills — " + listing),
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string",
                         "enum": [s["name"] for s in cat],
                         "description": "Which skill to load."},
                "guide": {"type": "string",
                          "description": ("Optional: a reference guide of that "
                                          "skill to read in full, by the name "
                                          "the skill listed. Omit to get the "
                                          "skill's instructions.")}},
                "required": ["name"]}},
    }


def skills_note(catalog=None):
    """The always-on listing of installed skills for the system prompt — the
    same thing Claude Code puts in an agent's context. A model does not go
    looking for a tool it was not told about, so the catalog is named every
    turn; the instructions themselves stay behind the tool call, so a skill
    costs context only when it is actually used."""
    cat = skill_catalog() if catalog is None else catalog
    if not cat:
        return ""
    lines = ["Skills available to you, loaded with the use_skill tool. Each is "
             "expert instructions for one job; when what he asks matches one, "
             "call use_skill FIRST and then follow it exactly, including its "
             "output contract:"]
    lines += ["- %s — %s" % (s["name"], s["description"]) for s in cat]
    return "\n".join(lines)

#: THE LONG WORK. `run_bash` is capped at 30 seconds by `sandbox-exec.py` —
#: right for a program that answers a question, useless for a job that maintains
#: his music library, which is what these exist for [his, 2026-08-23]. The four
#: are deliberately small in the schema: `run_job` is carried on every turn, the
#: other three are in the index and attach themselves the moment one is called.
JOB_TOOLS = [
    {"type": "function",
     "function": {
         "name": "run_job",
         "description": (
             "Run a long command in the BACKGROUND and get a job id back at "
             "once. Use this for anything that takes more than a few seconds — "
             "a library scan, a download, a transcode, a fingerprint pass — "
             "since run_bash is killed at 30 seconds. The job keeps running "
             "after this turn ends and after the window closes; check it with "
             "job_status and read it with job_log. Say the job id to him."),
         "parameters": {
             "type": "object",
             "properties": {
                 "command": {"type": "string",
                             "description": "The shell command to run."},
                 "label": {"type": "string",
                           "description": ("A few words naming the job, shown "
                                           "to him — e.g. 'fingerprint aud'.")},
                 "cwd": {"type": "string",
                         "description": "Directory to run in. Optional."},
                 "lang": {"type": "string", "enum": ["bash", "python"],
                          "description": "Default bash."}},
             "required": ["command", "label"]}}},
    {"type": "function",
     "function": {
         "name": "job_status",
         "description": ("How the background jobs are doing: state, exit code, "
                         "how long, and the last few lines of each. Pass an id "
                         "for one job, nothing for all of them."),
         "parameters": {"type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": []}}},
    {"type": "function",
     "function": {
         "name": "job_log",
         "description": ("Read a background job's output — the last `lines` of "
                         "it (default 80, max 400)."),
         "parameters": {"type": "object",
                        "properties": {"id": {"type": "string"},
                                       "lines": {"type": "integer"}},
                        "required": ["id"]}}},
    {"type": "function",
     "function": {
         "name": "job_stop",
         "description": "Stop a running background job by id.",
         "parameters": {"type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"]}}},
]
JOB_TOOL_NAMES = {t["function"]["name"] for t in JOB_TOOLS}

#: The tool that hands the model a tool. Its own schema is small on purpose —
#: it is paid for on every turn.
GET_TOOLS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_tools",
        "description": (
            "Attach one or more of the tools listed in 'Other tools' so you can "
            "call them, and get their full argument schemas back. Pass names "
            "(comma-separated) or a group. Do this the moment a job needs one; "
            "it costs one step and nothing else."),
        "parameters": {
            "type": "object",
            "properties": {
                "names": {"type": "string",
                          "description": ("Tool names or groups, comma-separated "
                                          "— e.g. 'lastfm, music_library' or "
                                          "'images'.")}},
            "required": ["names"]}}}
GET_TOOLS_TOOL_NAMES = {"get_tools"}


def tools_note(registry=None):
    """The ONE-LINE INDEX of every tool that is not in `CORE_TOOL_NAMES`.

    Same shape, and the same reason, as `skills_note`: a model does not reach
    for a door it was never told about, so every tool is named on every turn —
    but only its name and its first sentence, which is a few hundred tokens
    against the ~8.4k the full schemas cost. `get_tools` fetches the schema when
    one is actually wanted, and calling a listed tool directly works too:
    `_dispatch_tool` resolves by NAME, not by what the payload happened to
    offer, so a model that guesses the arguments right is not punished for it.
    """
    reg = Ollama._main_registry() if registry is None else registry
    rows = []
    for name in sorted(reg):
        if name in CORE_TOOL_NAMES:
            continue
        desc = str(reg[name].get("function", {}).get("description", "")).strip()
        line = re.split(r"(?<=[.!?])\s", desc)[0] if desc else ""
        line = " ".join(line.split())
        if len(line) > 90:
            line = line[:87].rstrip() + "…"
        rows.append("- %s — %s" % (name, line) if line else "- " + name)
    if not rows:
        return ""
    groups = sorted(set(AGENT_TOOL_GROUPS) | set(EXTRA_TOOL_GROUPS))
    return ("Other tools you have, not attached to this message. Call "
            "get_tools with the names (or a group: %s) to attach them and read "
            "their arguments — one step, then use them normally:\n%s"
            % (", ".join(groups), "\n".join(rows)))


# ---- subagents: definitions on disk, spawned with spawn_agent --------------
#
# A turn has ONE 32k window (CHAT_NUM_CTX) and MAX_TOOL_ROUNDS rounds to spend
# in it, and the expensive tool results are the ones worth least afterwards: a
# `search_text` over ~/nix or a `read_file` on a 260 KB source costs thousands
# of tokens to establish one fact. A SUBAGENT is the fix — its own message
# list, its own tool loop, its own context, and only its final answer comes
# back. That is the point of it here: not a smarter model, a SEPARATE window.
#
# It runs on the SAME served model by default, deliberately. A different model
# means ollama unloading the current weights and loading the other set — this
# desktop runs `OLLAMA_MAX_LOADED_MODELS=1` and the two biggest models here do
# not fit in RAM together — so a per-call model switch would pay two full
# reloads for one delegation. A definition may still NAME a model when the swap
# is worth it; nothing else does.

#: Where agent definitions live. chatter's canonical base is its OWN runtime
#: dir (`~/.local/share/oracle/agents`, override `$ORACLE_AGENTS`), like the
#: skills root — not `~/.claude/agents`, which belongs to Claude Code. The two
#: sets are deliberately separate. A definition file `<name>.md` REPLACES a
#: built-in of the same name, which is how he (or the model) edits a built-in
#: without touching main.py. Nothing here is vendored into this public repo.
#: TOOLS AS FILES [his, 2026-08-23]. Chatter's own answer, when he asked it
#: whether it could make its own tools, was "no — those are defined by the
#: framework I run in". This is that door: a directory of MANIFESTS, each naming
#: a program to run, loaded fresh every turn and offered beside the built-ins.
#: Nothing here is vendored and nothing is written by chatter — the directory is
#: HIS (and the model's, through the file tools it already has).
#:
#: One tool is `<name>.json`:
#:
#:     {"description": "What it does, written for the model.",
#:      "parameters": {"type": "object", "properties": {...}, "required": [...]},
#:      "run": "weather.sh",          // optional; default: <name>[.*] beside it
#:      "timeout": 30}                // optional seconds, capped at CUSTOM_MAX_SECS
#:
#: The program is run with the call's arguments as JSON on **stdin**; whatever
#: it prints on stdout is the result (parsed as JSON when it parses, text
#: otherwise), and a non-zero exit is an error carrying its stderr. That is the
#: same shape as every executor here, so a tool is a shell script that reads
#: stdin and prints — nothing to import, nothing to register.
CUSTOM_TOOLS_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_TOOLS", "~/.local/share/oracle/tools"))
#: A custom tool's answer is model context like any other: cap it.
CUSTOM_MAX_BYTES = 40000
CUSTOM_MAX_SECS = 300
CUSTOM_DEFAULT_SECS = 30


def custom_tools():
    """Every usable custom tool, as `{name: spec}`.

    A manifest that will not parse, names no runnable program, or collides with
    a BUILT-IN name is skipped rather than offered — a tool that cannot run is
    an affordance that is not there (docs/DESIGN.md §10). Read fresh on every
    turn, so adding one is saving a file, not restarting chatter."""
    out = {}
    try:
        files = sorted(Path(CUSTOM_TOOLS_ROOT).iterdir(), key=lambda f: f.name)
    except OSError:
        return out
    for f in files:
        if f.suffix != ".json" or not f.is_file():
            continue
        try:
            spec = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or f.stem).strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name or ""):
            continue
        run = str(spec.get("run") or "").strip()
        prog = None
        if run:
            cand = Path(run) if os.path.isabs(run) else f.parent / run
            prog = cand if cand.is_file() and os.access(cand, os.X_OK) else None
        else:
            for cand in sorted(f.parent.glob(f.stem + ".*")):
                if cand.suffix != ".json" and cand.is_file() and os.access(cand, os.X_OK):
                    prog = cand
                    break
            if prog is None and (f.parent / f.stem).is_file():
                cand = f.parent / f.stem
                prog = cand if os.access(cand, os.X_OK) else None
        if prog is None:
            continue
        params = spec.get("parameters")
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}}
        try:
            secs = float(spec.get("timeout") or CUSTOM_DEFAULT_SECS)
        except (TypeError, ValueError):
            secs = CUSTOM_DEFAULT_SECS
        out[name] = {"name": name, "prog": str(prog),
                     "description": str(spec.get("description") or
                                        ("custom tool " + name)),
                     "parameters": params,
                     "timeout": max(1.0, min(secs, CUSTOM_MAX_SECS))}
    return out


def custom_tool_defs(catalog=None):
    """The custom tools as function definitions, minus any name a built-in
    already owns — a custom `read_file` must never shadow the real one."""
    cat = custom_tools() if catalog is None else catalog
    return [{"type": "function",
             "function": {"name": t["name"],
                          "description": t["description"] + BUILT_BY_HIM,
                          "parameters": t["parameters"]}}
            for t in cat.values() if t["name"] not in BUILTIN_TOOL_NAMES]


#: Said on every custom tool, once: the model should know which of its tools are
#: the app's and which are his, because the failure modes differ (a built-in
#: that errors is a bug here; one of his that errors is a script to fix).
BUILTIN_TOOL_NAMES = set()          # filled once Ollama is defined, below


BUILT_BY_HIM = (" (A tool HE wrote and installed, not one of the app's own. If "
                "it fails, say what it printed — he can fix the script.)")


AGENTS_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_AGENTS", "~/.local/share/oracle/agents"))
#: One definition's prompt, capped like a skill's.
AGENT_MAX_CHARS = 40000
#: Rounds of tool calls ONE subagent may take before it has to answer. Lower
#: than MAX_TOOL_ROUNDS: a subagent is a bounded errand, and the parent still
#: has its own rounds left to spend on the answer.
AGENT_MAX_ROUNDS = 12
#: How much of the window a subagent may fill before it wraps up.
AGENT_CTX_FRACTION = 0.7
#: How much of a subagent's answer comes back. It exists to COMPRESS — an
#: agent that returns 40k of pasted file is the problem it was spawned to
#: solve — so the result is capped and says when it was cut.
AGENT_RESULT_CHARS = 12000
SPAWN_TOOL_NAMES = {"spawn_agent"}

#: The tools a definition may hand a subagent, by group, so a definition can
#: say `tools: read, exec` instead of naming ten. `all` is every one of them.
AGENT_TOOL_GROUPS = {
    "read": ["list_dir", "read_file", "find_files", "search_text", "show_tree"],
    "write": ["write_file", "edit_file", "move_path", "delete_path", "make_dir"],
    "exec": ["run_python", "run_bash"],
    "web": ["web_search", "fetch_url", "call_api"],
    "music": ["music_library", "lastfm", "control_media"],
    "sessions": ["list_sessions", "read_session"],
    "skills": ["use_skill"],
    "author": ["make_tool", "make_skill", "make_agent"],
    "time": ["get_current_time"],
    "jobs": ["run_job", "job_status", "job_log", "job_stop"],
}
#: THE TOOLS EVERY TURN CARRIES. The other two dozen are named in a one-line
#: index in the system prompt (`tools_note`) and attached on demand
#: (`get_tools`) — measured 2026-08-23: 39 schemas are 39,433 characters, 12.9k
#: tokens of a window that was 32k, which is most of why a music-library turn
#: ran out of room mid-answer. This set is what a turn reaches for without
#: being asked: the files, the shell, the web, the clock, and the two doors to
#: everything else (a skill, a subagent).
CORE_TOOL_NAMES = [
    "list_dir", "read_file", "find_files", "search_text",
    "write_file", "edit_file",
    "run_bash", "run_python",
    "web_search", "fetch_url",
    "get_current_time",
    "use_skill", "spawn_agent",
    "save_memory", "list_memories",
    "get_tools", "run_job",
    # THE GENERATORS ARE CORE, on his machine, because "make me a picture" is
    # a thing he asks in plain words and an unattached tool is one the model
    # has to go LOOKING for. On 2026-08-24 it went looking: it read the comfyui
    # skill, curled the backend, and told him the daemon did not exist and
    # painter was not installed — with both sitting right there. A tool that is
    # attached cannot be reasoned away.
    "make_image", "make_video",
]

#: Tool groups for `get_tools`, over and above `AGENT_TOOL_GROUPS`: the ones a
#: subagent never gets and so has no group of its own.
EXTRA_TOOL_GROUPS = {
    "jobs": ["run_job", "job_status", "job_log", "job_stop"],
    "images": ["fetch_image", "search_images", "view_image", "show_image",
               "make_image", "make_video", "screenshot", "booru_tags"],
    "video": ["show_video", "make_video"],
    "memory": ["save_memory", "list_memories", "delete_memory"],
    "models": ["manage_models"],
    "self": ["describe_self"],
}

#: What a subagent gets when its definition names no tools. Everything that
#: does real work and nothing that touches the WINDOW: the image tools render
#: into the transcript of the turn that spawned it and the memory tools write
#: what the main agent recalls, so both stay with the main agent. `spawn_agent`
#: is never in any set — subagents are one level deep, on purpose.
AGENT_TOOLS_DEFAULT = (AGENT_TOOL_GROUPS["read"] + AGENT_TOOL_GROUPS["write"]
                       + AGENT_TOOL_GROUPS["exec"] + AGENT_TOOL_GROUPS["web"]
                       + AGENT_TOOL_GROUPS["skills"] + AGENT_TOOL_GROUPS["author"]
                       + AGENT_TOOL_GROUPS["time"])

#: Always present, whether or not anything is installed on disk — a spawn that
#: names nothing still has to work, and an empty agents directory should not
#: mean an empty menu (docs/DESIGN.md §10). A file of the same name in
#: AGENTS_ROOT replaces the built-in outright, which is how he (or the model)
#: edits one of these without touching this source.
BUILTIN_AGENTS = [
    {"name": "general",
     "description": ("A capable all-rounder: files, shell, python and the web. "
                     "Use it when no other agent fits."),
     "tools": list(AGENT_TOOLS_DEFAULT),
     "prompt": ("You are a capable general worker. Use the tools you have to "
                "establish facts rather than assuming them, and report what "
                "you actually found.")},
    {"name": "explorer",
     "description": ("Reads and searches the filesystem and reports back. "
                     "Read-only — it cannot write, delete or run anything. Use "
                     "it to answer 'where is X / how does Y work / which files "
                     "do Z' without pulling every file into your own context."),
     "tools": list(AGENT_TOOL_GROUPS["read"]),
     "prompt": ("You are a code and filesystem explorer. Search widely, read "
                "only the parts that matter, and come back with the ANSWER — "
                "the file paths and line numbers that establish it, and a "
                "short explanation. Quote only the lines that carry the point; "
                "never paste a whole file back. If a tree has an AGENTS.md or "
                "CLAUDE.md, read it: it states the rules of that tree.")},
    {"name": "coder",
     "description": ("Makes a scoped code change and verifies it: reads, "
                     "edits, runs it. Give it one concrete change with enough "
                     "context to act, not a whole project."),
     "tools": (AGENT_TOOL_GROUPS["read"] + AGENT_TOOL_GROUPS["write"]
               + AGENT_TOOL_GROUPS["exec"] + AGENT_TOOL_GROUPS["skills"]),
     "prompt": ("You are a careful programmer. Read the file before you change "
                "it and match the style around your edit. Prefer edit_file to "
                "rewriting a file whole. After every change, CHECK it — run "
                "it, import it, diff it — and report what the check actually "
                "printed. Never delete or move anything you were not asked to. "
                "If a tree has an AGENTS.md or CLAUDE.md, read it first and "
                "follow it. Report what you changed, file by file, and say so "
                "plainly if you could not finish.")},
    {"name": "researcher",
     "description": ("Searches the public web and reads the pages, then "
                     "summarises with links. No filesystem, no shell."),
     "tools": (AGENT_TOOL_GROUPS["web"] + AGENT_TOOL_GROUPS["time"]),
     "prompt": ("You are a researcher. Search, then actually READ the promising "
                "pages with fetch_url rather than answering off the snippets. "
                "Come back with the answer, what is uncertain about it, and the "
                "links that support it. Say when the sources disagree.")},
]

#: What every subagent is told before its own definition: what it is, who reads
#: its answer, and that it cannot come back for a decision. A subagent asking a
#: clarifying question is a wasted spawn — nobody is there to answer it.
AGENT_SYSTEM_PREFIX = (
    "You are a SUBAGENT. Another model — the one talking to the user — spawned "
    "you to do one job and is waiting on the result; the user cannot see this "
    "conversation and cannot answer you. So: do not ask questions, do not "
    "offer to proceed, and do not describe a plan. Do the job with the tools "
    "you have, in this turn, and then write your FINAL ANSWER as your whole "
    "reply. That answer is the only thing that comes back, so make it "
    "self-contained: the finding itself, the paths, numbers or commands that "
    "establish it, and anything that went wrong. Be complete but compact — you "
    "exist so the model that spawned you does not have to read everything you "
    "read. If you could not do it, say exactly what stopped you.")


def _front_matter(text):
    """`(fields, body)` from a leading `---` YAML block: every `key: value` in
    it (folded continuation lines joined), and the text with the block
    stripped. No YAML parser — the shape is fixed and stdlib-only is the rule
    for everything chatter reads (same reasoning as `_skill_front`, which is
    now this)."""
    if not text.startswith("---"):
        return ({}, text)
    end = text.find("\n---", 3)
    if end < 0:
        return ({}, text)
    head = text[3:end]
    body = text[end + 4:].lstrip("\n")
    fields, key = {}, ""
    for line in head.splitlines():
        if re.match(r"^\s+\S", line) and key:
            fields[key] = (fields[key] + " " + line.strip()).strip()
            continue
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        fields[key] = val
    return (fields, body)


def _agent_tool_names(spec_tools):
    """A definition's `tools:` field -> a list of tool names chatter has.

    Accepts group names (`read`, `exec`, …), individual tool names, `all`, and
    anything else — a Claude Code definition naming ITS tool names, say — which
    is ignored. An entry that resolves to nothing falls back to the default
    set: an agent that can do nothing at all is never what was meant, and
    silently producing one is exactly the affordance dishonesty docs/DESIGN.md
    §10 forbids."""
    if not spec_tools:
        return list(AGENT_TOOLS_DEFAULT)
    if isinstance(spec_tools, str):
        parts = [p.strip() for p in re.split(r"[,\s]+", spec_tools) if p.strip()]
    else:
        parts = [str(p).strip() for p in spec_tools if str(p).strip()]
    if any(p.lower() == "all" for p in parts):
        return list(AGENT_TOOLS_DEFAULT)
    out = []
    for p in parts:
        low = p.lower()
        if low in AGENT_TOOL_GROUPS:
            out += AGENT_TOOL_GROUPS[low]
        elif p in _tool_registry():
            out.append(p)
    seen, uniq = set(), []
    for n in out:
        if n not in seen and n not in SPAWN_TOOL_NAMES:
            seen.add(n)
            uniq.append(n)
    return uniq or list(AGENT_TOOLS_DEFAULT)


def _tool_registry():
    """`{name: schema}` for every tool a SUBAGENT could be given. Built from the
    same objects the main payload carries, so the two cannot drift; spawn_agent
    itself is absent, which is what keeps subagents one level deep."""
    tools = (list(FILE_TOOLS) + [WEB_SEARCH_TOOL, TIME_TOOL, FETCH_URL_TOOL,
             CALL_API_TOOL, EXEC_TOOL, BASH_TOOL, SHOW_IMAGE_TOOL,
             MUSIC_TOOL, LASTFM_TOOL, PLAYER_TOOL] + list(JOB_TOOLS)
             + list(SESSION_TOOLS) + list(AUTHOR_TOOLS)
             + [t for t in [skill_tool()] if t]
             + custom_tool_defs())
    return {t["function"]["name"]: t for t in tools
            if isinstance(t, dict) and isinstance(t.get("function"), dict)}


def agent_files():
    """Every readable `*.md` agent definition, sorted by name. Absent root -> []."""
    try:
        return sorted((f for f in Path(AGENTS_ROOT).iterdir()
                       if f.is_file() and f.suffix == ".md"), key=lambda f: f.name)
    except OSError:
        return []


def agent_catalog():
    """Every agent that can be spawned: the built-ins, with any definition file
    of the same name replacing one outright, plus every other file found.

    A definition is `<name>.md` — optional `---` frontmatter (`description`,
    `tools`, `model`) and then the body, which IS the agent's system prompt.
    Nothing here is vendored and nothing is written by chatter: the directory
    is his (and the model's) to edit with the file tools it already has."""
    out = {a["name"]: dict(a) for a in BUILTIN_AGENTS}
    order = [a["name"] for a in BUILTIN_AGENTS]
    for f in agent_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")[:AGENT_MAX_CHARS]
        except OSError:
            continue
        fields, body = _front_matter(text)
        name = (fields.get("name") or f.stem).strip()
        if not name or not body.strip():
            continue
        if name not in out:
            order.append(name)
        out[name] = {
            "name": name,
            "description": (fields.get("description") or "").strip()
                           or "A custom agent defined in " + str(f),
            "tools": fields.get("tools", ""),
            "model": (fields.get("model") or "").strip(),
            "prompt": body.strip(),
            "path": str(f),
        }
    return [out[n] for n in order]


def agent_spec(name, catalog=None):
    """One agent by name, with its tool names resolved. An unknown name (or
    none) resolves to the first built-in rather than failing: the model asked
    for help with a job, and refusing over a label helps nobody."""
    cat = agent_catalog() if catalog is None else catalog
    pick = next((a for a in cat if a["name"] == (name or "").strip()), None)
    if pick is None:
        pick = cat[0]
    spec = dict(pick)
    spec["tool_names"] = _agent_tool_names(spec.get("tools"))
    return spec


def spawn_agent_tool(catalog=None):
    """The `spawn_agent` function tool, built from the agents actually present
    — the `agent` enum names them, so the model cannot spawn one that is not
    defined."""
    cat = agent_catalog() if catalog is None else catalog
    if not cat:
        return None
    listing = "; ".join("%s: %s" % (a["name"], a["description"]) for a in cat)
    return {
        "type": "function",
        "function": {
            "name": "spawn_agent",
            "description": (
                "Hand one self-contained job to a SUBAGENT and get back only "
                "its answer. The subagent gets its own fresh context and its "
                "own rounds of tool calls; everything it reads, greps and runs "
                "stays in ITS context, and only the answer lands in yours. "
                "Use it when the job would otherwise flood this conversation "
                "with output you do not need to keep — searching a large tree, "
                "reading several files to establish one fact, a long build or "
                "test run — and when the job can be stated completely up "
                "front, because the subagent cannot ask you anything. Do the "
                "work yourself when it is small, when you need to see the raw "
                "output, or when it needs the conversation you are in. Give "
                "`task` everything it needs: absolute paths, the exact "
                "question, and what a good answer looks like. Agents available "
                "— " + listing),
            "parameters": {"type": "object", "properties": {
                "agent": {"type": "string",
                          "enum": [a["name"] for a in cat],
                          "description": "Which agent to spawn."},
                "task": {"type": "string",
                         "description": ("The whole job, stated so someone who "
                                         "cannot see this conversation could do "
                                         "it: what to do, where, and what to "
                                         "report back.")},
                "context": {"type": "string",
                            "description": ("Optional: facts from this "
                                            "conversation the subagent needs "
                                            "and has no way to discover.")}},
                "required": ["agent", "task"]}},
    }


def agents_note(catalog=None):
    """The always-on listing of agents for the system prompt — the same reason
    skills are named every turn: a model does not spawn something it was never
    told about. It also says where the definitions LIVE and what shape they
    are, because the file tools already reach that directory — writing one is
    how the model gives itself, and the next agent, a new specialist [his,
    2026-08-23: "make it easier for oracle agents to modify themselves and
    future / other agents"]."""
    cat = agent_catalog() if catalog is None else catalog
    if not cat:
        return ""
    lines = ["Subagents you can spawn with the spawn_agent tool. Each one runs "
             "in its OWN context and returns only its final answer, so use one "
             "to keep bulky work out of this conversation:"]
    lines += ["- %s — %s" % (a["name"], a["description"]) for a in cat]
    lines.append(
        "These are files: %s/<name>.md, with optional `---` frontmatter "
        "(`description:` one line; `tools:` any of %s, individual tool names, "
        "or `all`; `model:` an installed ollama model) and the body as that "
        "agent's system prompt. You have file tools, so you can write one. Do "
        "that when a job keeps recurring and none of the above fits it, or "
        "when one of them keeps getting something wrong — edit its file and "
        "the next spawn uses the new version. Say so when you do; do not "
        "rewrite an agent he is relying on without telling him."
        % (AGENTS_ROOT, ", ".join(sorted(AGENT_TOOL_GROUPS))))
    return "\n".join(lines)


# ---- self-authoring: the model writes its own tools, skills and agents -----
#
# Everything above is something the model can USE. This is the door the other
# way [his, 2026-08-23]: a tool it can call to write a NEW tool, skill or
# subagent definition, for itself and for every future turn and agent. It could
# already do it with `write_file` — the notes say where the files live and what
# shape they are — but a tool is not a file, it is a manifest plus an
# executable plus a JSON schema, and a model that gets one of the three subtly
# wrong produces something that silently never loads. So the shape is written
# HERE, validated, and reported back as live or not at all (docs/DESIGN.md §10).
#
# All three stores are read fresh every turn (`custom_tools`, `skill_catalog`,
# `agent_catalog`), so what it writes is live on the NEXT round of the same
# turn — no restart, and no rebuild.
AUTHOR_MAX_CODE = 100000
AUTHOR_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

AUTHOR_TOOLS = [
    {"type": "function", "function": {
        "name": "make_tool",
        "description": (
            "Write a NEW TOOL for yourself — one you and every future "
            "conversation and subagent can then call like any built-in. Use it "
            "when a job keeps coming back and no tool fits it: the thing you "
            "would otherwise re-write as run_bash/run_python every time. You "
            "give it a name, the description the model reads to decide when to "
            "call it, a JSON-schema `parameters` object, and the program. The "
            "program is run with the call's arguments as JSON on stdin and "
            "whatever it prints on stdout is the result (JSON if it parses, "
            "text otherwise); a non-zero exit is an error carrying its stderr. "
            "The tool is live from your very next tool call — say so, and say "
            "what you made. Pass `delete` to remove one you wrote."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": (
                "Tool name: lowercase letters, digits, _ and -, up to 64. It "
                "cannot be one of the app's own tool names.")},
            "description": {"type": "string", "description": (
                "What the tool does and when to call it, written for a model "
                "choosing between tools. This is all a future you will know "
                "about it.")},
            "parameters": {"type": "object", "description": (
                "JSON Schema for the call arguments: {\"type\": \"object\", "
                "\"properties\": {...}, \"required\": [...]}. Omit for a "
                "tool that takes none.")},
            "language": {"type": "string", "enum": ["python", "bash"],
                         "description": "What the program is written in."},
            "code": {"type": "string", "description": (
                "The program. It reads the arguments as JSON on stdin and "
                "prints the result on stdout. A shebang is added if you leave "
                "it out.")},
            "timeout": {"type": "number", "description": (
                "Optional seconds before the tool is killed (default %d, max "
                "%d)." % (CUSTOM_DEFAULT_SECS, CUSTOM_MAX_SECS))},
            "delete": {"type": "boolean", "description": (
                "Delete this tool instead of writing it.")}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "make_skill",
        "description": (
            "Write a NEW SKILL — expert instructions for one job, which you "
            "and every future conversation load with use_skill. Use it when "
            "you have worked out HOW to do something well (a format he wants, "
            "a procedure that took several tries to get right) and want the "
            "next you to start from it rather than rediscover it. The "
            "description is what a future model reads to decide whether the "
            "job matches; the instructions are what it then follows. Pass "
            "`delete` to remove one."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": (
                "Skill name: lowercase letters, digits, _ and -.")},
            "description": {"type": "string", "description": (
                "One line: when this skill applies. It is listed in every "
                "future turn's context, so make it say what job it is for.")},
            "instructions": {"type": "string", "description": (
                "The skill itself: what to do, step by step, and what the "
                "output must look like. Markdown.")},
            "delete": {"type": "boolean",
                       "description": "Delete this skill instead of writing it."}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "make_agent",
        "description": (
            "Write a NEW SUBAGENT DEFINITION — a named specialist you and "
            "future conversations can hand a job to with spawn_agent. Use it "
            "when a kind of errand keeps recurring and none of the existing "
            "agents fits, or to fix one that keeps getting something wrong "
            "(write it again with the same name to replace it). Pass `delete` "
            "to remove one you wrote; the app's own built-in agents come back "
            "when their file is deleted."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": (
                "Agent name: lowercase letters, digits, _ and -.")},
            "description": {"type": "string", "description": (
                "One line: what this agent is for. It is listed in every "
                "future turn's context and is how a model picks it.")},
            "prompt": {"type": "string", "description": (
                "The agent's system prompt: who it is, how it should work, "
                "and what its final answer must contain.")},
            "tools": {"type": "string", "description": (
                "Optional: which tools it gets — any of the groups (%s), "
                "individual tool names, or `all`. Omit for the default set."
                % ", ".join(sorted(AGENT_TOOL_GROUPS)))},
            "model": {"type": "string", "description": (
                "Optional: an installed ollama model to run it on. Omit to "
                "run it on the model you are — a swap costs a full reload.")},
            "delete": {"type": "boolean",
                       "description": "Delete this definition instead of writing it."}},
            "required": ["name"]}}},
]
AUTHOR_TOOL_NAMES = {"make_tool", "make_skill", "make_agent"}


def authoring_note():
    """The always-on line telling the model it can EXTEND itself, and where
    each store lives. Same reasoning as `skills_note`/`agents_note`: a model
    does not reach for a door it was never told about — chatter's own answer,
    when he asked whether it could make its own tools, was "no, those are
    defined by the framework I run in" [his, 2026-08-23]."""
    return ("You can extend yourself, permanently, and every future "
            "conversation and subagent inherits what you write:\n"
            "- make_tool writes a new TOOL (stored in %s) — a program you can "
            "call like any built-in.\n"
            "- make_skill writes a new SKILL (%s) — instructions a future you "
            "loads with use_skill.\n"
            "- make_agent writes a new SUBAGENT (%s) — a specialist to hand "
            "jobs to with spawn_agent.\n"
            "All three are live from your next tool call, with nothing "
            "restarted. Do it when a job keeps recurring, when you had to work "
            "out how to do something and the next you should start from it, or "
            "when he asks for it — and TELL him what you wrote, in a line. Do "
            "not replace something he relies on without saying so."
            % (CUSTOM_TOOLS_ROOT, SKILLS_ROOT, AGENTS_ROOT))


#: How many tool rounds one turn may take before the wrap-up round makes it
#: answer with what it has. This is a RUNAWAY guard, not a work budget: at 4 it
#: was the work budget, and a real job — find a directory, read three files,
#: edit one, check the edit — ran out of rounds mid-task, so he had to press
#: `continue` over and over to get one task done [his, 2026-08-23: "i shouldnt
#: have to keep clicking continue for the agent to do its task"]. The thing that
#: actually has to stop a turn is the CONTEXT filling up (`_ctx_room` below),
#: which is measured rather than guessed at; this number is only the backstop
#: for a model looping on the same call forever, and he can always press stop.
MAX_TOOL_ROUNDS = 24

#: How much of `CHAT_NUM_CTX` the conversation may fill before the tool loop
#: wraps up. Past this the next round would be truncated by the server anyway
#: (this model's KV cache does not context-shift), so the turn is better spent
#: writing the answer than on one more tool call whose result will not fit.
TOOL_CTX_FRACTION = 0.75

#: How full `CHAT_NUM_CTX` has to get before a round counts as having hit the
#: ceiling (`_truncation_reason`). ollama's own accounting is prompt + generated
#: tokens, so the last round before the wall lands a hair under it rather than
#: exactly on it — 98% is "there was no room left", not a guess at one.
CTX_FULL_FRACTION = 0.98

#: How many characters of PAST turns' tool output the next turn may carry.
#:
#: Until 2026-08-22 the answer was zero, and it is what wrecked a real session
#: [his]: the message list handed to the model was rebuilt every turn from the
#: chat log alone (`_parse_history` keeps user/assistant TEXT and nothing else),
#: so every tool call and every tool result died with the turn that made it. An
#: agent asked to change something in `~/nix` therefore re-read the same files
#: on every turn and every `continue`, re-derived the same conclusion five times
#: in one conversation, and never got as far as the edit. Tools were never the
#: missing piece — working memory was.
#:
#: The budget is charged NEWEST FIRST and the rest is stubbed rather than
#: dropped (see `_trim_carry`), because the shape of the exchange — which tool
#: was called, with which arguments — is what stops the model repeating itself,
#: and that lives on the assistant message, which is always kept. 12k chars is
#: ~3k tokens against a 32k window: a real memory that cannot crowd out the
#: conversation it belongs to.
TOOL_CARRY_CHARS = 12000

#: What a stubbed-out old tool result says in its place.
TOOL_CARRY_STUB = ("[earlier output dropped to save context — the call above is "
                   "what you ran; call it again if you need the output back]")

#: The recall guidance, on the system prompt of EVERY turn. Without it the model
#: treats a fact it does not see in the CURRENT chat as unknown — or, worse, as
#: something it must have made up — and denies it, even though he told it in an
#: earlier conversation and list_sessions/read_session can reach that chat. This
#: tells the model those past sessions are its own genuine memory of real
#: conversations with the same person, to be consulted and TRUSTED (never
#: dismissed as a hallucination) before it says it does not know something —
#: especially personal facts like his name or his preferences.
RECALL_GUIDANCE = (
    "You are talking with the same person across many separate conversations, "
    "and you can read your earlier ones: call list_sessions to see your past "
    "conversations with him and read_session to read any of them in full. "
    "Those transcripts are a real record of things he actually told you — treat "
    "anything he stated there as true, not as something you imagined. When he "
    "refers to something you do not see in the current conversation (his name, a "
    "preference, an earlier decision), do NOT assume you never knew it or that it "
    "is a hallucination: look through your recent past sessions first, and only "
    "say you do not know it once you have checked and genuinely cannot find it.")

#: On every turn too: tells the model it MAY, and should, save durable facts on
#: its OWN initiative — not only when asked to remember something. Without this
#: the model treats save_memory as something it does when told; a test where it
#: was expected to keep a fact it had just learned "could not", because nothing
#: authorised it to write one unprompted. This makes proactive saving explicit
#: (still bounded to lasting facts, not chat trivia, matching the tool's own
#: description). It is guidance, not a mechanism: a model with no tool support
#: still cannot call the tool at all — point chatter at a tool-capable model.
SAVE_GUIDANCE = (
    "You may save durable facts to your memory on your own initiative — you do "
    "not need to be asked. Whenever he tells you something lasting (his name, a "
    "preference, an ongoing project, a decision) or you learn a fact worth "
    "keeping across conversations, call save_memory to record it right then, "
    "without announcing it. Save only lasting things, not one-off details of the "
    "current chat, and update or delete a memory with save_memory/delete_memory "
    "when it changes or turns out wrong.\n"
    "BEFORE YOU FINISH A TURN, ask yourself whether it contained anything of "
    "that kind, and if it did, call save_memory then — permission alone has not "
    "been enough: the store held two memories across weeks of conversations "
    "that were full of things worth keeping [his, 2026-08-22]. It costs one "
    "tool call and he never sees it. Worth keeping: how he works, what he is "
    "building, a correction he gave you, a tool or path that turned out to "
    "matter, something he asked you to do differently. Not worth keeping: what "
    "was said this turn, anything already in the list above (check it first — "
    "update the existing memory instead of adding a near-duplicate), and "
    "anything you are guessing at.")

#: On every turn: an HONEST, static summary of what this app actually lets the
#: model do, so it reports its abilities correctly instead of guessing from
#: training (gemma4:e4b told him it "has no code-execution env" — true at the
#: time, but it reached for it blind rather than from its real tool inventory,
#: and that gap is what the board question of 2026-08-11 closed with `run_python`).
#: describe_self gives the exact live tool list on demand; a model does not call
#: it spontaneously, so the families it has — and the LIMITS on them — are named
#: here too (docs/DESIGN.md §10 affordance honesty: never imply an ability that
#: silently is not there, in either direction, and never overstate a jail).
CAPABILITY_NOTE = (
    "What you can actually do in this app, through function tools offered every "
    "turn: search the public web; READ a web page or JSON URL by link "
    "(fetch_url); fetch and display images; PLAY A VIDEO inline "
    "(show_video — a YouTube or other watch page, or a direct video "
    "file, streamed into the chat with a play button he presses); "
    "read the current time in any "
    "timezone; INSTALL AND MANAGE THE MODELS THEMSELVES (manage_models: list, "
    "show, pull a new one from the ollama library with progress, remove one) — "
    "use it rather than `ollama` in a shell; "
    "SEARCH HIS MUSIC LIBRARY and put something on (music_library "
    "finds tracks and albums with their paths; control_media play_these / "
    "queue_these plays or queues them); "
    "SHOW him a picture that is already on the machine (show_image — "
    "for a chart you plotted or a file you found: it costs you nothing and "
    "needs no vision); GENERATE one (make_image, his own image backend); LOOK "
    "AT HIS SCREEN (screenshot); SEE AND CONTROL ANY MEDIA (control_media — "
    "what is playing, pause, skip, seek, volume, on the machine this window "
    "runs on); read a "
    "file's real type, size, duration, codecs and TAGS without opening it "
    "(file_metadata); read, write, edit, move, delete and search files on the host — "
    + ("the WHOLE filesystem, not a sandbox, exactly what the user himself can "
       "touch" if WRITE_FREE else
       "reading anywhere, writing only inside your own sandbox directory") +
    " (files he drags onto the window are staged for you too); read your "
    "past conversations; save, list and delete your own durable memories; load "
    "a SKILL (use_skill) — expert instructions for one job, listed for you "
    "below; SPAWN A SUBAGENT (spawn_agent) to do a bulky job in its own "
    "context and hand you back only the answer, and write or edit the agent "
    "definitions those are built from; RUN Python code (run_python); and RUN "
    "BASH (run_bash) — a real "
    "shell, so grep, find, sed, cp, mv, git and pipelines of them are how you "
    "do file work, not something you only describe. Both runners execute on the "
    "host as the user, with the network up, killed after a few seconds and "
    "capped in CPU and memory. That reach is real and so is the damage it can "
    "do: look at a file before you overwrite it, prefer editing to replacing, "
    "never delete or move anything you did not create unless he asked for it in "
    "this conversation, and say what you changed. Nothing you run is confirmed "
    "first and nothing is undone. You cannot use root (there is no sudo). "
    "Describe your abilities in these terms, and call "
    "describe_self for the exact live tool list — never claim a capability you "
    "do not have, and never deny one you do. Some of the tools you are offered "
    "are HIS: he writes them as scripts in a directory and they appear beside "
    "the app's own (their descriptions say so). You can read and write that "
    "directory with the file tools, so if a job needs a tool that does not "
    "exist, you can propose one — or write it.")

#: FINISH THE JOB. A model that treats one tool round as one turn stops after a
#: look-around and describes what it would do next, which left him pressing
#: `continue` to get a single task done [his, 2026-08-23]. It has MAX_TOOL_ROUNDS
#: rounds of tool calls per turn and should spend them on the task.
PERSISTENCE_NOTE = (
    "Finish the job in THIS turn. You get many rounds of tool calls before you "
    "have to answer \u2014 around %d \u2014 so keep going until the task is "
    "actually done: look, act, then CHECK what you did. Do not stop to announce "
    "a plan, to ask whether to proceed with something he already asked for, or "
    "to say what you would do next; do it. Come back early only if you "
    "genuinely need a decision from him, or the job is done. "
    "And do not narrate your work as you go: write NO prose before a tool "
    "call \u2014 just make the call \u2014 and give ONE final message at the "
    "end covering the result. A preamble restating your plan is a whole bubble "
    "he has to read that the answer then repeats; the tool activity is already "
    "shown to him separately." % MAX_TOOL_ROUNDS)

#: The app's own notes inside the conversation, and the rule that they are not
#: his words. A turn that made a picture or a clip carries a
#: `[image in this chat: /path · WxH]` line in the history so the path survives
#: a restart (Root.qml `mediaNote`) — and a model reading it verbatim back at
#: him is a line of app plumbing in the middle of an answer, which is what
#: happened the first day it existed [2026-08-24].
MARKER_NOTE = (
    "Lines in square brackets like `[image in this chat: /path]`, "
    "`[video in this chat: /path]` and `[attached: name]` are the APP telling "
    "you what is already on screen and where it is on disk. They are not his "
    "words and he cannot see them as text. Use the paths — they are what "
    "you pass as first_frame, input_images or to view_image — but never "
    "quote, repeat or print one in your answer, and never present one as a "
    "link.")

#: How many times a turn may carry ITSELF on before it has to hand back. A
#: model that announces its next step instead of taking it is the single reason
#: he was pressing `continue` over and over [his, 2026-08-23: "its still
#: stopping mid generation and making me press continue over and over again"] —
#: PERSISTENCE_NOTE asks it not to, and gemma4 does it anyway. So the app
#: presses the button for him, a bounded number of times.
AUTO_CONTINUE_MAX = 3

#: A reply that ANNOUNCES work rather than doing it. Matched against the tail of
#: a finished answer: "I'll now grep for…", "The next step is…". Deliberately
#: narrow — an answer that simply ENDS matches nothing here, and a genuine
#: question to him ("which of these two do you want?") is not an announcement of
#: the model's own next action.
#:
#: `shall i` / `would you like me to` / `should i proceed` used to be in this
#: list, and they are the reason a `hello` turned into five rounds that queued a
#: track he never asked for [his, 2026-08-23]. Those are not announcements, they
#: are the model WAITING ON HIM, and the app answered them for him with
#: `proceed`. A question is never carried on: see `looksUnfinished`.
UNFINISHED_PATTERNS = [
    r"\b(i'?ll|i will|i'?m going to|i am going to|let me|i'?d like to)\b"
    r"[^.?!\n]{0,90}\b(now|next|then|proceed|start|begin|run|execute|check|"
    r"verify|read|edit|write|create|search|grep|look|inspect|apply|use)\b",
    r"\bproceed(ing)? (with|to)\b",
    r"\bthe (next|final) step\b",
    r"\bstand by\b",
]

#: How wide a web search fans out, scaled to the query's apparent complexity
#: (see `Ollama._research_budget`). A simple factual ask (a weather lookup, a
#: definition) needs a handful of sources; a genuinely broad research question
#: may want many. The number of Tavily results per search is capped to one of
#: these, and the model is TOLD in the system prompt how much fan-out this ask
#: warrants — so a "10 hour weather report" no longer pulls 20 sources, while a
#: real research question can still go wide. Never below RESEARCH_MIN (some
#: sources are always useful) nor above RESEARCH_MAX (context guard).
RESEARCH_MIN = 3
RESEARCH_MAX = 8

#: The context window (tokens) to request per chat. Ollama's own default (4096
#: here, set by the model's Modelfile/server default, well under the 262144 a
#: model like qwen3.6:35b-a3b actually supports) is small enough that the
#: system prompt + tool schemas + history + a couple of tool results (a session
#: read pulls in a whole past transcript) can fill it mid-turn — and this
#: server's KV cache does not support context-shift for this model ("KV cache
#: shifting is not supported for this context"), so a turn that outgrows 4096
#: is hard-truncated wherever it happens to be, including mid-thinking, with
#: only a handful of tokens left to generate. Asking for a much larger window
#: costs little (the KV cache for this model is ~80 MiB at 4096, so 32768 is
#: still well under a gigabyte) and turns a hard cutoff into headroom.
#:
#: It is now the FLOOR and the fallback, not the answer: `CtxFit` sizes the
#: window per model against the memory this machine actually has (see below).
CHAT_NUM_CTX = 32768

#: The most any turn may ask for, however much memory is free. The KV cache is
#: allocated up front and ollama honours an oversized `num_ctx` by spilling
#: model layers to RAM rather than by shrinking the window (measured 2026-08-23:
#: qwen3.5:4b at 262144 went from 3.1 GB resident to 13.7 GB, half of it off the
#: GPU) — so the ceiling is a deliberate number, not the hardware's limit.
CHAT_NUM_CTX_CAP = 131072

#: SAMPLER DEFAULTS, BY FAMILY. Chatter used to send none at all, which means
#: whatever the model's own Modelfile carries — fine for a model published with
#: good ones, wrong for a raw GGUF imported from HuggingFace, which is exactly
#: how the two Gemma 4 entries arrived (2026-08-23). Google publishes Gemma's:
#: temperature 1.0, top_k 64, top_p 0.95, min_p 0.0. The key is matched against
#: the model name, longest first, and anything unmatched is left alone —
#: silence is the right default for a model whose author already tuned it.
SAMPLER_DEFAULTS = {
    "gemma4": {"temperature": 1.0, "top_k": 64, "top_p": 0.95, "min_p": 0.0},
    "gemma3": {"temperature": 1.0, "top_k": 64, "top_p": 0.95, "min_p": 0.0},
}


def sampler_for(model):
    """The sampling options to send with `model`, or {} for leave-it-alone."""
    name = (model or "").lower()
    for key in sorted(SAMPLER_DEFAULTS, key=len, reverse=True):
        if key in name:
            return dict(SAMPLER_DEFAULTS[key])
    return {}


#: The windows that may actually be asked for. Steps, because changing
#: `num_ctx` makes ollama reload the model — see `CtxFit.numCtx`.
CTX_LADDER = (32768, 65536, 131072)

#: How much of the free memory a KV cache may claim. Half: the other half is the
#: turn's own growth, whatever the warden has not seen yet, and the fact that
#: `MemAvailable` is a forecast rather than a promise.
CTX_FIT_SAFETY = 0.5

#: Left on the GPU whatever happens — the compositor and every other client draw
#: out of the same VRAM.
VRAM_HEADROOM = 512 * 1024 * 1024

#: The floor the warden frees at (`home/srvs/ai-warden.nix`). A window is never
#: sized into it: this app asking for 128k is not a reason for the desktop to
#: start swapping.
CTX_RAM_FLOOR = 6 * 1024 * 1024 * 1024

#: What `CtxFit` has learned, per model: bytes of KV cache per token, measured
#: from ollama's own load. Small enough to rewrite whole.
CTX_FIT_STORE = os.path.expanduser(
    os.environ.get("ORACLE_CTXFIT", "~/.local/share/oracle/ctxfit.json"))

#: The file tools' JAIL. Every file op runs against this one directory and
#: cannot escape it (tools/sandbox-fs.py enforces it, symlinks included). It is
#: the ONLY thing to change to widen the sandbox later ("maybe we let it run
#: free") — point ORACLE_SANDBOX at ~ or / and the tools reach further, no code
#: change. It lives on TOP, where oracle's ollama compute is: expanded here to
#: an absolute /home/lam/... path (identical on both machines, user `lam`) so it
#: needs no shell tilde-expansion when handed to top over ssh.
SANDBOX_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_SANDBOX", "~/.local/share/oracle/sandbox"))

#: The READ jail — WIDER than SANDBOX_ROOT: the whole filesystem, root '/'
#: (widened from just his home, 2026-08-11). The read-only file ops (list_dir/
#: read_file/find_files/search_text/show_tree) resolve against this instead, so
#: the model can READ anything on the machine while write/edit/move/delete stay
#: confined to SANDBOX_ROOT; the read ops still cannot escape THIS root either
#: (symlinks included — tools/sandbox-fs.py enforces it per-root), '/' just
#: happens to make that a no-op. Point ORACLE_READ_ROOT at SANDBOX_ROOT to
#: restore the old jailed-reads behaviour, or at his home to restore the
#: 2026-08-11 scope. Applies on whichever machine the executor actually runs
#: on — see `host` on the read tools and `Ollama._fs_argv` for reading the
#: OTHER machine from here.
READ_ROOT = os.path.expanduser(os.environ.get("ORACLE_READ_ROOT", "/"))

#: The jailed executor. Same absolute path on top and book (the repo lives at
#: /home/lam/nix on both), so `python3 <this>` runs unchanged locally on top or
#: over ssh to top from book. Pure stdlib — top's system python3 runs it.
FS_SCRIPT = str(HERE / "tools" / "sandbox-fs.py")

#: The named-session store. ONE canonical location so both machines share one
#: set of conversations rather than a per-machine split ("for now", his words).
#: Like the file-tool sandbox it lives where oracle's compute is — on `top` —
#: run locally there and over the tunnel's ssh master from `book`
#: (`Sessions._store_argv`, host-branched exactly like the file tools). Absolute
#: /home/lam/... path (identical on both, user `lam`) so it needs no shell
#: tilde-expansion when handed to top over ssh. Override with $ORACLE_SESSIONS.
SESSIONS_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_SESSIONS", "~/.local/share/oracle/sessions"))
SESSIONS_SCRIPT = str(HERE / "tools" / "sessions-store.py")

#: BACKGROUND JOBS — the work that outlives the turn (tools/job-run.py). Same
#: place and the same host rule as the sandbox: it lives on TOP, where oracle's
#: compute is, run locally there and over the tunnel's ssh from `book`.
JOBS_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_JOBS", "~/.local/share/oracle/jobs"))
JOBS_SCRIPT = str(HERE / "tools" / "job-run.py")

#: How often the window re-reads the job directory. Two seconds is a readout
#: that keeps up with a running log without being a poll anyone notices; a
#: window with no jobs in it asks a third as often.
JOBS_POLL_MS = 2000
JOBS_IDLE_POLL_MS = 6000

#: Lines of a job's log kept on its row.
JOBS_TAIL = 12

#: oracle's OWN memory store — the durable facts it manages itself (MEMORY_TOOLS
#: above). One `memories.json` under this root, driven through
#: tools/memory-store.py exactly like the session store, and living in the same
#: canonical place on `top` (run locally there, over the tunnel's ssh from
#: `book`) so both machines share one set of memories. Absolute /home/lam/...
#: path (identical on both, user `lam`) so it needs no tilde-expansion over ssh.
#: Override with $ORACLE_MEMORY.
MEMORY_ROOT = os.path.expanduser(
    os.environ.get("ORACLE_MEMORY", "~/.local/share/oracle/memory"))
MEMORY_SCRIPT = str(HERE / "tools" / "memory-store.py")

#: The code runner. Same absolute path on both machines and pure stdlib, so
#: `python3 <this> <sandbox>` runs unchanged locally on top or over ssh from
#: book — identical to FS_SCRIPT. Runs against SANDBOX_ROOT (the WRITE jail):
#: the sandbox is the code's working directory, so files it writes relatively
#: sit beside what the file tools see.
EXEC_SCRIPT = str(HERE / "tools" / "sandbox-exec.py")
#: Whether run_python may reach the network — YES since 2026-08-22, with the
#: rest of the unjailing (`ORACLE_EXEC_NET=0` cuts it again, which is the
#: `unshare -rn` the runner used to do unconditionally). A code runner that
#: could write his whole filesystem but not open a socket would be theatre.
EXEC_NET = os.environ.get("ORACLE_EXEC_NET", "1") not in ("0", "false", "no")

#: How much of the memory store to inject into each turn's system prompt (newest
#: first): a bound so a large store can never crowd out the conversation. The
#: store itself caps at 500 entries; this caps what any single turn carries.
MEMORY_CTX_MAX = 60
MEMORY_CTX_CHARS = 8000

#: Which machine we run on, by OS hostname (`top` / `book`) — NOT the flake
#: attribute. On `book` there is no local `ollama.service`; the daemon lives on
#: `top` and oracle reaches both its HTTP API (over the tunnel that forwards
#: 11434, tools/ollama-tunnel.sh) and — for start/stop — its systemd unit over
#: the same ssh. See Backend below.
ON_BOOK = socket.gethostname() == "book"

#: oracle's own config dir (shared with tavily.key). Two optional, no-rebuild
#: files drive the model selector — drop them in and relaunch, same as the key:
#:   `last-model`     one line, the model to pre-select next launch. oracle
#:                    writes it on every pick/send, so the last model he used is
#:                    the default the next time he opens the window.
#:   `suggested.json` a JSON array of model names AGENTS write to recommend a
#:                    model. Those present in /api/tags are ranked ABOVE the rest
#:                    of the dropdown, in the file's order (see apps/oracle/AGENTS.md).
#: `$ORACLE_CONFIG` moves the whole directory, which is what a harness points
#: somewhere disposable — his base prompt and his last model are HIS, and a
#: selftest that pokes the Settings menu must not write them (root AGENTS.md →
#: "Testing without interfering with the user"; one did, once).
CONFIG_DIR = Path(os.path.expanduser(
    os.environ.get("ORACLE_CONFIG", "~/.config/oracle")))
LAST_MODEL_PATH = CONFIG_DIR / "last-model"
#: HOW LOUD A CLIP PLAYS, for every clip [his, 2026-08-24: "if the user sets
#: the volume of one clip it sets the same volume for every other past and
#: future clip"]. One number, 0..1, in its own file beside the others — the
#: transports all read the same one, so setting it on any card sets it on the
#: card three replies up as well as on the next one.
VIDEO_VOLUME_PATH = CONFIG_DIR / "video-volume"

#: What a soundless copy of a clip is called, beside the original — the same
#: name painter gives it (`apps/painter/main.py`, MUTED_TAG), so the two apps
#: reuse each other's copy instead of each making one.
MUTED_TAG = "-muted"
SUGGESTED_PATH = CONFIG_DIR / "suggested.json"

#: The chosen base system prompt, persisted like `last-model`: one small JSON,
#: `{"choice": <preset id or "custom">, "custom": <the user's own text>}`. The
#: `custom` text is kept even while a preset is active, so switching back to it
#: does not lose what he wrote. Missing/malformed → the built-in default (no
#: base). This is the ONLY user-facing base text; whatever it resolves to is
#: prepended ahead of the time line + memory block + recall/save guidance, which
#: ALWAYS run regardless of which base is active (see `_system_prompt`).
SYSPROMPT_PATH = CONFIG_DIR / "system-prompt.json"

#: The built-in base-prompt presets, selectable in the UI, with `custom` (his
#: own text) offered alongside them. `default` is empty — the historical
#: behaviour, no leading base at all. The id is stored; the label is shown; the
#: text is what gets prepended. Kept deliberately short and host-neutral (no
#: machine deixis — this list syncs to both hosts). Order here is the UI order.
PROMPT_PRESETS = [
    {"id": "default", "label": "Default (no persona)", "text": ""},
    {"id": "concise", "label": "Concise", "text": (
        "Answer as briefly as the question allows. Lead with the answer, skip "
        "preamble and filler, and stop once it is said. Use a list only when it "
        "genuinely reads better than a sentence.")},
    {"id": "coder", "label": "Coding assistant", "text": (
        "You are a pragmatic programming assistant. Prefer correct, idiomatic "
        "code that matches the surrounding style, and show it in fenced blocks "
        "with the language tagged. Explain only what is not obvious from the "
        "code, name the trade-off when there is one, and say plainly when "
        "something will not work rather than guessing.")},
    {"id": "tutor", "label": "Socratic tutor", "text": (
        "You are a patient tutor. Build understanding step by step, check what "
        "he already knows, and prefer a guiding question or a small worked "
        "example over a wall of exposition. Correct mistakes gently and "
        "concretely.")},
    {"id": "writer", "label": "Creative writer", "text": (
        "You are a sharp creative writer. Favour vivid, concrete language and a "
        "clear voice over cliché and hedging. Match the tone and length he asks "
        "for, and when a prompt is open-ended, make a strong choice rather than "
        "offering a menu.")},
    {"id": "casual", "label": "Casual companion", "text": (
        "You are a warm, easygoing friend to chat with. Keep it relaxed and "
        "conversational — plain everyday language, a bit of personality, no "
        "lecturing and no corporate polish. Match his energy, ask a friendly "
        "follow-up when it fits, and don't pad short exchanges with formality. "
        "Still be honest and helpful when he actually needs something.")},
]
PROMPT_PRESET_IDS = {p["id"] for p in PROMPT_PRESETS}


def tavily_key():
    """The Tavily API key, never hardcoded (see apps/oracle/AGENTS.md).

    Same shape as `OLLAMA` reads its endpoint: an env var first
    (`TAVILY_API_KEY`), then a convenience fallback file so the key can be set
    without a rebuild — `~/.config/oracle/tavily.key`, one line, the key. Empty
    string when neither is present; the tool then reports itself unavailable."""
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if key:
        return key
    try:
        return (Path.home() / ".config" / "oracle" / "tavily.key"
                ).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---- the wallpaper palette (mirrors reader/viewer/filer — see reader/main.py) --
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml and kept in
    sync via a filesystem watch (identical to reader's and viewer's)."""

    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        d = os.path.dirname(self._path)
        if os.path.isdir(d):
            self._watcher.addPath(d)   # dir watch catches atomic replaces
        self._rewatch()
        self._load()

    def _rewatch(self):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)

    def _on_change(self, _):
        self._rewatch()
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return
        colors = dict(self._colors)
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            name, val = m.group(1), m.group(2)
            if name in PALETTE_KEYS:
                colors[name] = val
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


class Clip(QObject):
    """Copy out of the chat log — text with its MARKDOWN still on it, and the
    pictures and clips in it as real files.

    A reply is drawn through `MarkdownText.qml`, so what Qt puts on the
    clipboard for Ctrl+C is the RENDERED document flattened to plain text: the
    blank line between two paragraphs becomes one newline, list bullets lose
    their markers, and a video prompt pasted into another program arrives as
    one run-on block [his, 2026-08-22]. What he wants back is what the model
    actually wrote.

    So the copy is served from the markdown SOURCE instead:

      * a whole-message selection (Ctrl+A, or a drag over all of it) copies the
        source string verbatim — no re-serialisation, nothing to get wrong;
      * a partial selection is re-serialised out of the document fragment
        (`QTextDocument.toMarkdown`), which is exact for the structure Qt itself
        parsed and keeps the paragraph breaks a plain-text copy drops.

    It is the clipboard proper, not the primary selection: a middle-click paste
    still gets whatever the item's own selection handling put there.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._procs = set()       # a QProcess with no Python ref is collected

    @Slot(QObject, int, int, str, result=bool)
    def copyMarkdown(self, quick_doc, start, end, source):
        from PySide6.QtGui import QTextCursor, QTextDocument
        if quick_doc is None or end <= start:
            return False
        doc = quick_doc.textDocument()
        if doc is None:
            return False
        # `characterCount()` counts the trailing block terminator, so a full
        # selection ends one short of it.
        whole = start <= 0 and end >= doc.characterCount() - 1
        if whole and source:
            text = source
        else:
            cur = QTextCursor(doc)
            cur.setPosition(start)
            cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            tmp = QTextDocument()
            QTextCursor(tmp).insertFragment(cur.selection())
            # Qt escapes anything that COULD be markup on the way out, so a
            # `<Picture 1>` or a `[Shot 1]` in a prompt comes back as
            # `\<Picture 1>` / `\[Shot 1]`. Undo that: the text he is pasting
            # is going somewhere that wants it as the model wrote it.
            text = re.sub(r"\\([\\`*_{}\[\]()#+.!<>-])", r"\1",
                          tmp.toMarkdown()).rstrip("\n")
        if not text:
            return False
        QGuiApplication.clipboard().setText(text)
        return True

    @Slot(str, result=bool)
    def copyText(self, text):
        """A whole message, verbatim — the log's right-click "copy message".

        Deliberately not `copyMarkdown` with a full range: the caller already
        HAS the source string (a reply's markdown, a prompt's plain text), so
        there is no document to re-serialise and nothing to get wrong.
        """
        if not text:
            return False
        QGuiApplication.clipboard().setText(text)
        return True

    # ---- a picture or a clip, OUT of the chat -----------------------------
    #
    # He asked to be able to copy what is in the log and paste it elsewhere, the
    # generated ones above all [his, 2026-08-24]. Both go through
    # `pylib/clipfile.py`, never QClipboard, for the two reasons the rest of
    # this desktop already pays for (apps/AGENTS.md → `pylib/`):
    #
    #   * A Wayland selection DIES WITH THE PROCESS that offered it. Copy a
    #     picture, close chatter, paste — nothing. clipfile forks a holder that
    #     outlives us and lets go when something else takes the clipboard.
    #   * `QClipboard.setMimeData` hands Qt's global-static clipboard a
    #     Python-built QMimeData it frees AFTER the interpreter is gone — a
    #     SIGSEGV on exit from any run that copied.
    #
    # `--image` additionally offers the file's own bytes under its image mime,
    # so a paste lands as the picture in an editor and as the file (with its
    # name) anywhere that understands one. A VIDEO gets the file offer alone —
    # there is no "the picture" to hand over.

    copied = Signal(str, bool)     # message for the toast, and whether it failed

    @Slot(str)
    def copyImage(self, path):
        self._copy_file(path, True)

    @Slot(str)
    def copyFile(self, path):
        self._copy_file(path, False)

    # A SILENT COPY OF A CLIP, the way painter has offered one since 2026-08-06
    # [his, 2026-08-24]. The video models generate sound with the picture and it
    # is usually not what the clip is wanted for — dropping one into a browser
    # or a chat is a page that starts making noise. Same rule as painter's
    # `copyMuted`: `<name>-muted.mp4` beside the original, REUSED when it is
    # already there and not older than the source (asking twice must not leave
    # three files), and a `-c copy` remux rather than an encode, so it runs at
    # IO speed and the picture is bit-identical.
    @Slot(str)
    def copyMutedVideo(self, path):
        raw = str(path or "")
        if raw.startswith("file://"):
            raw = QUrl(raw).toLocalFile()
        src = Path(os.path.abspath(os.path.expanduser(raw))) if raw else None
        if src is None or not src.exists():
            self.copied.emit("can't copy it: it is gone", True)
            return
        if src.stem.endswith(MUTED_TAG):
            self._copy_file(str(src), False)
            return
        dest = src.with_name(src.stem + MUTED_TAG + src.suffix)
        try:
            fresh = dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime
        except OSError:
            fresh = False
        if fresh:
            self._copy_file(str(dest), False)
            return
        proc = QProcess(self)
        self._procs.add(proc)

        def finished(code, _status):
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            self._procs.discard(proc)
            proc.deleteLater()
            if code == 0 and dest.exists():
                self._copy_file(str(dest), False)
            else:
                self.copied.emit("could not mute it: " + (err.splitlines()[-1]
                                                          if err else
                                                          "exit %d" % code), True)

        def failed(_e):
            if proc in self._procs:
                self._procs.discard(proc)
                proc.deleteLater()
                self.copied.emit("could not mute it: no ffmpeg", True)

        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        # -map 0 -map -0:a keeps everything that is not audio; -dn drops the
        # data streams an mp4 copy otherwise refuses. The same command painter
        # and filer's videoconv use.
        proc.start("ffmpeg", ["-hide_banner", "-nostdin", "-y",
                              "-loglevel", "error", "-i", str(src),
                              "-map", "0", "-map", "-0:a", "-c", "copy", "-dn",
                              "-movflags", "+faststart", str(dest)])

    def _copy_file(self, path, as_image):
        raw = str(path or "")
        if raw.startswith("file://"):
            raw = QUrl(raw).toLocalFile()
        src = os.path.abspath(os.path.expanduser(raw)) if raw else ""
        name = os.path.basename(src) or "it"
        if not src or not os.path.exists(src):
            self.copied.emit("can't copy " + name + ": it is gone", True)
            return
        argv = ([sys.executable, str(CLIPFILE)]
                + (["--image"] if as_image else []) + [src])
        proc = QProcess(self)
        self._procs.add(proc)

        def finished(code, _status):
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            if code == 0:
                self.copied.emit("copied " + name, False)
            else:
                self.copied.emit("copy failed: " + (err.splitlines()[-1] if err
                                                    else "exit %d" % code), True)
            self._procs.discard(proc)
            proc.deleteLater()

        def failed(_e):
            if proc in self._procs:
                self.copied.emit("copy failed: cannot run clipfile", True)
                self._procs.discard(proc)
                proc.deleteLater()

        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        proc.start(argv[0], argv[1:])


class MdFormat(QObject):
    """Make a rendered reply's CODE BLOCKS sit inside the bubble.

    Qt's markdown reader gives every fenced block `NonBreakableLines`, so a long
    line does not wrap — it lays out past the item's width and paints across
    whatever is beside it, straight out of the bubble [his, 2026-08-22]. Nothing
    in QML reaches that flag: it is on the QTextDocument's block formats, which
    is why this lives here rather than in `MarkdownText.qml`.

    So the same document the item is already drawing is walked once and each
    code block is (a) allowed to wrap and (b) given the background and the
    margins that make it read as an embedded block rather than as loose
    monospace. The TEXT is untouched — no re-wrapping of the source, no inserted
    newlines — so `Clip.copyMarkdown` still hands over exactly what the model
    wrote.

    It is idempotent and reports whether it CHANGED anything, which is what
    keeps a `textChanged` handler from looping on its own edits.
    """

    #: Our own durable mark on a block we have already unwrapped — the flag Qt
    #: set is gone by then, and nothing else on a QTextBlockFormat says "this
    #: was fenced". QTextFormat.UserProperty + 7 is ours; Qt uses none of it.
    CODE_MARK = 0x100000 + 7

    #: How far one block stands off the one above it. Qt gives every block 6px
    #: top AND bottom, which collapse to a 6px gap — a paragraph break that
    #: reads no stronger than a wrapped line [his, 2026-08-23]. The gap is on
    #: the TOP margin only (adjacent margins collapse to the larger of the two,
    #: so one side is enough) and the first block of a reply gets none, or every
    #: bubble would open with a blank strip.
    PARA_TOP = 12          # between paragraphs: most of a line, not a whole one
    HEAD_TOP = 16          # a heading stands further off what came before it
    LIST_TOP = 2           # bullets are ONE list, not a stack of paragraphs

    @Slot(QObject, result=str)
    def styleCode(self, quick_doc):
        """Let every fenced block wrap, and say WHERE the blocks are.

        Returns a JSON array of `{start, end}` character positions, one entry
        per run of code lines, so the item can draw a panel behind each one —
        the tint cannot be done here. Qt Quick's text nodes paint a CHARACTER
        format's background and ignore a BLOCK format's (measured: a block
        background drew nothing), and a char background stops at the end of each
        line, which leaves a ragged strip rather than an embedded block.

        Idempotent: the flag is cleared on the first pass and the RANGES are
        found by the monospace family Qt gives a code block, which survives it.
        """
        from PySide6.QtGui import QTextCursor
        if quick_doc is None:
            return "[]"
        doc = quick_doc.textDocument()
        if doc is None:
            return "[]"
        runs = []
        block = doc.begin()
        while block.isValid():
            fmt = block.blockFormat()
            # A FENCED block, by the flag Qt itself sets on one — and by our own
            # mark once that flag is gone, since clearing it is the point.
            #
            # NOT by the monospace family: a paragraph that merely BEGINS with
            # an inline `code` span reports monospace as its block char format,
            # which drew a whole prose line as an embedded code panel (measured
            # against the demo transcript).
            code = fmt.hasProperty(self.CODE_MARK) or fmt.nonBreakableLines()
            # The gap above this block. A code block is left alone: `styleCode`
            # sees one block PER LINE inside a fence, so a margin here would
            # space the code out line by line.
            if not code:
                if block.blockNumber() == 0:
                    top = 0
                elif block.textList() is not None:
                    top = self.LIST_TOP
                elif fmt.headingLevel() > 0:
                    top = self.HEAD_TOP
                else:
                    top = self.PARA_TOP
                # Only when it differs: setBlockFormat marks the document
                # changed, and the caller re-runs this on every change.
                if fmt.topMargin() != top or fmt.bottomMargin() != 0:
                    fmt.setTopMargin(top)
                    fmt.setBottomMargin(0)
                    QTextCursor(block).setBlockFormat(fmt)
            if code:
                if fmt.nonBreakableLines() or not fmt.hasProperty(self.CODE_MARK):
                    fmt.setNonBreakableLines(False)
                    fmt.setProperty(self.CODE_MARK, True)
                    fmt.setLeftMargin(6)
                    fmt.setRightMargin(6)
                    QTextCursor(block).setBlockFormat(fmt)
                start = block.position()
                end = block.position() + block.length() - 1
                if runs and runs[-1]["endBlock"] == block.blockNumber() - 1:
                    runs[-1]["end"] = end
                    runs[-1]["endBlock"] = block.blockNumber()
                else:
                    runs.append({"start": start, "end": end,
                                 "endBlock": block.blockNumber()})
            block = block.next()
        for r in runs:
            r.pop("endBlock", None)
        return json.dumps(runs)


class Titlebar(QObject):
    """hyprvtb app-button bridge — oracle draws no chrome of its own, so the
    compositor draws the titlebar (docs/DESIGN.md §12). oracle has no history and
    no view modes, so it registers with the defaults and no buttons; the window
    title is still drawn by the plugin. The one thing it publishes is a FOOTER
    naming the connected daemon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = VtbClient()

    @Slot(str)
    def setFooter(self, text):
        self._client.set_footer(text)


class Jobs(QObject):
    """The background jobs, as the window sees them.

    Everything real lives in `tools/job-run.py` and in the job directory it
    writes (see that file); this is a readout over it — a poll, a list QML
    draws, and four verbs. Nothing here holds a process: a job survives this
    window closing, and a relaunch picks the running ones back up because it
    reads the same directory.

    The host branch is the one every executor here uses: local on `top`, over
    the tunnel's ssh master from `book`, so the work always runs where the
    library and the compute are.
    """

    rowsChanged = Signal()
    jobFinished = Signal(str, str, int)   # label, state, exit code

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._states = {}          # id -> the state we last told anyone about
        self._proc = None          # the live `list` poll
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self.jobFinished.connect(self.notify)
        self._timer.start(JOBS_IDLE_POLL_MS)
        self.refresh()

    # ---- the argv, host-branched exactly like the file and exec tools ----

    @staticmethod
    def _argv(*args):
        if ON_BOOK:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            return argv + [host, "python3", shlex.quote(JOBS_SCRIPT)] + \
                [shlex.quote(str(a)) for a in args]
        return [sys.executable, JOBS_SCRIPT] + [str(a) for a in args]

    def _run(self, *args, timeout=15000):
        """One job-run.py call, synchronously. Milliseconds locally; the only
        caller that could feel an ssh round trip is a tool, which is already
        waiting on a model."""
        proc = QProcess()
        argv = self._argv(*args)
        proc.start(argv[0], argv[1:])
        if not proc.waitForFinished(timeout):
            proc.kill()
            return {"error": "job command timed out"}
        out = bytes(proc.readAllStandardOutput().data()).decode("utf-8",
                                                               "replace")
        try:
            return json.loads(out or "{}")
        except ValueError:
            err = bytes(proc.readAllStandardError().data()).decode(
                "utf-8", "replace").strip()
            return {"error": (err or out or "job command failed")[:400]}

    # ---- the poll ----

    @Slot()
    def refresh(self):
        if self._proc is not None:
            return                              # one in flight is enough
        proc = QProcess(self)
        self._proc = proc
        argv = self._argv("list", JOBS_ROOT, "--tail", JOBS_TAIL)
        proc.finished.connect(lambda *_: self._on_list(proc))
        proc.start(argv[0], argv[1:])

    def _on_list(self, proc):
        if proc is not self._proc:
            return                    # a duplicate `finished`, or a torn-down app
        self._proc = None
        # RuntimeError: the app is being torn down and the C++ QProcess is
        # already gone. A poll landing during teardown is not an error worth
        # printing at him.
        try:
            out = bytes(proc.readAllStandardOutput().data()).decode(
                "utf-8", "replace")
            rows = json.loads(out or "{}").get("jobs") or []
        except (ValueError, RuntimeError):
            rows = self._rows
        try:
            proc.deleteLater()
        except RuntimeError:
            pass
        # SAY WHEN ONE ENDS. A job runs for an hour; the row going quiet is not
        # enough on its own (docs/DESIGN.md §10 — the state is shown, and the
        # end of a long wait is the state that matters most).
        for r in rows:
            was = self._states.get(r["id"])
            now = r.get("state")
            if was and was != now and now in ("done", "failed", "stopped",
                                              "timeout"):
                self.jobFinished.emit(r.get("label") or "job", now,
                                      int(r.get("exit") or 0))
        self._states = {r["id"]: r.get("state") for r in rows}
        running = any(r.get("state") in ("running", "starting") for r in rows)
        try:
            self._timer.setInterval(JOBS_POLL_MS if running
                                    else JOBS_IDLE_POLL_MS)
        except RuntimeError:
            return                    # the app is going away underneath us
        if rows != self._rows:
            self._rows = rows
            self.rowsChanged.emit()

    # ---- a finished job says so, when the window cannot ----

    @Slot(str, str, int)
    def notify(self, label, state, code):
        """A desktop notification for a job that ended while he was elsewhere.

        A job runs for an hour — the window it started in may be behind three
        others by the time it finishes, and the tray row going still is only
        visible to someone looking at it (docs/DESIGN.md §10). Skipped when
        chatter is the active window, because then the row IS the notification.

        `--` before the positionals: notify-send parses a summary starting with
        `-` as an option and exits 1 with no id, which reads exactly like a
        missing notification daemon.
        """
        # A HARNESS NEVER NOTIFIES HIM. `tools/jobs-test.py` starts real jobs
        # and finishes them; on 2026-08-23 that put "job stopped · sleeper" and
        # "job failed · orphan" toasts on his screen while he was working —
        # a test reaching the live session, which is a bug in the test path,
        # not the price of testing (root AGENTS.md).
        if SELFTEST or os.environ.get("ORACLE_NO_NOTIFY"):
            return
        if QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive:
            return
        if not shutil.which("notify-send"):
            return
        body = {"done": "finished", "failed": "failed (exit %d)" % code,
                "stopped": "stopped", "timeout": "hit its time limit"}.get(
                    state, state)
        urgency = "normal" if state == "done" else "critical"
        proc = QProcess(self)
        proc.startDetached("notify-send",
                           ["-a", "chatter", "-u", urgency,
                            "-i", "media-playlist-repeat", "--",
                            "job " + body, str(label)])

    # ---- what QML draws ----

    @Property("QVariantList", notify=rowsChanged)
    def rows(self):
        return self._rows

    @Property(int, notify=rowsChanged)
    def runningCount(self):
        return sum(1 for r in self._rows
                   if r.get("state") in ("running", "starting"))

    # ---- the verbs (QML and the tools use the same four) ----

    def start(self, command, lang="bash", cwd="", label="", max_seconds=0):
        args = ["start", JOBS_ROOT, "--command", command,
                "--lang", "python" if lang == "python" else "bash",
                "--label", label or "job"]
        if cwd:
            args += ["--cwd", cwd]
        if max_seconds:
            args += ["--max-seconds", int(max_seconds)]
        out = self._run(*args)
        self.refresh()
        return out

    def status(self, job_id="", tail=JOBS_TAIL):
        args = ["list", JOBS_ROOT, "--tail", int(tail)]
        if job_id:
            args += ["--id", job_id]
        return self._run(*args)

    @Slot(str, result="QVariant")
    def stop(self, job_id):
        out = self._run("stop", JOBS_ROOT, "--id", job_id)
        self.refresh()
        return out

    @Slot(str, result="QVariant")
    @Slot(result="QVariant")
    def clear(self, job_id=""):
        args = ["clear", JOBS_ROOT]
        if job_id:
            args += ["--id", job_id]
        out = self._run(*args)
        self.refresh()
        return out


class CtxFit(QObject):
    """How big a context window THIS machine can actually give THIS model.

    The window used to be a flat `CHAT_NUM_CTX` for every model on either
    machine, and the stat line showed the model's TRAINED ceiling beside it —
    262144 for qwen3.6:35b-a3b, when what it was running in was 32768 [his,
    2026-08-23: *"can you make the context indicator represent the REAL amount
    of context i have based on my system specs for the given model?"*].

    **The KV cache is the only thing that scales with the window**, and its size
    per token is not derivable from `/api/show`: a hybrid-attention model
    reports `head_count_kv: null` and gives no count of which of its layers
    actually hold KV (qwen3.6 keeps 10 of 40, so every metadata estimate is 4x
    out — in the direction that would have SHRUNK his window to ~9k). So it is
    not estimated. **It is read from ollama's own load**, which prints the
    figure exactly:

        llama_kv_cache: size = 640.00 MiB ( 32768 cells, 10 layers, 1/1 seqs)

    — 20 KiB per token for that model. One measurement per model, cached in
    `CTX_FIT_STORE`, and a model never yet measured simply gets `CHAT_NUM_CTX`,
    which is what every model got before this existed. Nothing here can make the
    window smaller than it used to be.

    On `book` there is no local `ollama.service` to read a journal from (the
    daemon runs on `top`, over the tunnel), so calibration never happens there
    and the fallback is the whole behaviour.
    """

    #: ollama's KV line: total size, then the cell count it covers.
    KV_LINE = re.compile(
        r"llama_kv_cache:\s+size\s*=\s*([\d.]+)\s*MiB\s*\(\s*(\d+)\s*cells")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._kv = self._load()      # model -> bytes of KV per token
        self._procs = []             # live journalctl QProcesses
        self._asked = set()          # models a calibration has been tried for

    # ---- the store ----

    def _load(self):
        try:
            with open(CTX_FIT_STORE, encoding="utf-8") as f:
                obj = json.load(f)
            return {str(k): float(v) for k, v in obj.items()
                    if isinstance(v, (int, float)) and v > 0}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(CTX_FIT_STORE), exist_ok=True)
            with open(CTX_FIT_STORE, "w", encoding="utf-8") as f:
                json.dump(self._kv, f, indent=1)
        except OSError:
            pass

    # ---- what the machine has free ----

    @staticmethod
    def _mem_available():
        try:
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        return 0

    @staticmethod
    def _vram_free():
        """Free VRAM in bytes, or 0 when there is no NVIDIA GPU to ask (book).

        Synchronous on purpose — it runs once per turn, next to a chat request
        that takes seconds, and `nvidia-smi` answers in tens of milliseconds.
        """
        if not shutil.which("nvidia-smi"):
            return 0
        proc = QProcess()
        proc.start("nvidia-smi", ["--query-gpu=memory.free",
                                  "--format=csv,noheader,nounits"])
        if not proc.waitForFinished(4000) or proc.exitCode() != 0:
            return 0
        try:
            out = bytes(proc.readAllStandardOutput().data()).decode(
                "utf-8", "replace")
            return int(out.strip().split("\n")[0].strip()) * 1024 * 1024
        except (ValueError, IndexError, RuntimeError):
            return 0

    # ---- the answer ----

    def numCtx(self, model, trained=0, loaded=False, weights=0):
        """The window to ask for, in tokens.

        `trained` is the model's own ceiling (`/api/show`), `loaded` says
        whether its weights are already resident — an unloaded model has to pay
        for them out of the same budget — and `weights` is its file size.
        """
        kv = self._kv.get(str(model or ""), 0.0)
        if kv <= 0:
            fit = CHAT_NUM_CTX               # never measured: as it always was
        else:
            budget = self._vram_free() - VRAM_HEADROOM
            budget += max(0, self._mem_available() - CTX_RAM_FLOOR)
            if not loaded:
                budget -= max(0, int(weights))
            fit = int(max(0, budget) * CTX_FIT_SAFETY / kv)
            # A LADDER, NOT A MEASUREMENT, is what gets asked for: ollama
            # RELOADS the model whenever `num_ctx` changes, so a window that
            # tracked free memory exactly would reload 24 GB of weights every
            # time a browser tab closed. Doubling steps are far apart compared
            # with that jitter.
            fit = max((r for r in CTX_LADDER if r <= fit), default=0)
        fit = max(CHAT_NUM_CTX, min(fit, CHAT_NUM_CTX_CAP))
        if trained > 0:
            fit = min(fit, int(trained))
        return fit

    def known(self, model):
        return self._kv.get(str(model or ""), 0.0) > 0

    # ---- the measurement ----

    @Slot(str, int)
    def calibrate(self, model, context_length):
        """Learn this model's bytes-per-token from ollama's own load log.

        Only ever called for a model that IS loaded, with the window `/api/ps`
        says it was loaded in — the cell count in the log line has to match it,
        which is what keeps a stale line from an earlier load (or another
        model's) from being read as this one's.
        """
        model = str(model or "")
        cells = int(context_length or 0)
        if not model or cells <= 0 or self.known(model) or model in self._asked:
            return
        if ON_BOOK or not shutil.which("journalctl"):
            return
        self._asked.add(model)
        proc = QProcess(self)
        self._procs.append(proc)

        def done():
            try:
                text = bytes(proc.readAllStandardOutput().data()).decode(
                    "utf-8", "replace")
            except (RuntimeError, ValueError):
                text = ""
            for m in reversed(self.KV_LINE.findall(text)):
                mib, n = float(m[0]), int(m[1])
                if n == cells and mib > 0:
                    self._kv[model] = mib * 1024 * 1024 / n
                    self._save()
                    break
            if proc in self._procs:
                self._procs.remove(proc)

        proc.finished.connect(done)
        proc.start("journalctl", ["-u", "ollama.service", "-n", "3000",
                                  "--no-pager", "-o", "cat"])


class Ollama(QObject):
    """The whole ollama seam: the model list and one streamed chat turn.

    `refreshModels` GETs `/api/tags`; `send` POSTs a single-turn `/api/chat`
    with `stream: true` and emits each NDJSON delta as it arrives, so QML never
    parses the wire — it receives `replyStarted` / `replyChunk` / `replyDone`,
    or `replyError` with a reason it can draw (docs/DESIGN.md §10: an action that
    cannot be reported must say so, not silently do nothing). One turn at a
    time: a new `send` aborts any reply still streaming."""

    modelsChanged = Signal()
    lastModelChanged = Signal()
    promptChanged = Signal()      # the chosen base prompt or its custom text
    busyChanged = Signal()
    modelsError = Signal(str)

    replyStarted = Signal()
    replyChunk = Signal(str)
    replyThinking = Signal(str)   # a "thinking" model's reasoning deltas
    replyThinkTokens = Signal(int)  # running count of reasoning tokens this turn
    replyDone = Signal()
    #: The reply STOPPED SHORT — ollama's own `done_reason`, so far only
    #: "length" (the model hit its token ceiling mid-sentence). QML draws a
    #: `continue` on that row rather than leaving him a half-sentence with no
    #: way on (docs/DESIGN.md §10 — the state is shown, and it is actionable).
    replyTruncated = Signal(str)
    #: The finished reply, REWRITTEN — a typed `{{show_video|…}}` marker becomes
    #: the bare URL once the card is drawn from it. QML replaces the row's body.
    replyBodyFixed = Signal(str)
    replyError = Signal(str)

    # The web_search tool-call loop, surfaced so QML can draw a subordinated
    # "sources" disclosure per turn (docs/DESIGN.md §9.1): the model asked to
    # search, the search returned N sources (as themed-link markdown), or it
    # failed with a reason.
    webSearchStarted = Signal(str)          # query
    webSearchDone = Signal(str, str, int)   # query, sources markdown, result count
    webSearchError = Signal(str, str)       # query, reason

    # The file-tool activity, surfaced so QML can draw the same subordinated
    # per-turn disclosure the web search gets (docs/DESIGN.md §9.1, §10 — the
    # model touching files is shown, never silent): one op began, and one
    # finished with a short outcome line and whether it succeeded.
    fileToolStarted = Signal(str)           # a short "read notes.md" heading
    fileToolDone = Signal(str, bool)        # outcome line, ok

    # The generic per-round tool indicator (docs/DESIGN.md §9.1, §10 — every tool
    # the model calls is shown, named, never silent). Emitted once per call for
    # EVERY tool in a round, before it is dispatched, so a tool with no richer
    # disclosure of its own (get_current_time, describe_self, a future one) still
    # surfaces in the transcript. The rich blocks above (web sources, files,
    # inline images) remain the DETAIL view for the tools that have one.
    toolCallStarted = Signal(str)           # the tool name

    # DELEGATION, drawn as its own disclosure rather than folded into the file
    # block it used to borrow (docs/DESIGN.md §9.1, §10). A spawn is not a file
    # op: it is a second context doing minutes of work whose only visible trace
    # was one line saying it had finished. So: it announces itself with the task
    # and, when the definition names one, the model it is about to make ollama
    # swap in; it reports every round and every tool the subagent calls, so the
    # wait is not silent and the main agent's own tool count stays honest; and
    # what it ANSWERED is shown, that being the one thing that says whether the
    # delegation was worth it.
    agentStarted = Signal(str, str, str)    # agent name, task, model if it differs
    agentProgress = Signal(str, int, str)   # agent name, round, the tool it called
    agentDone = Signal(str, bool, str)      # agent name, ok, the block to draw

    #: A NEW TOOL ROUND is about to generate. Emitted after a round's results
    #: are back and before the next POST, so QML can close the row that round
    #: wrote into and open a fresh one: one bubble per round, instead of every
    #: round's prose and every round's tools piling into one bubble with the
    #: final answer, where it was impossible to see where a round began [his,
    #: 2026-08-23]. The int is the round about to start (the prompt's own
    #: first generation is round 1, so a tool round is always 2 or more).
    roundStarted = Signal(int)

    # The image-fetch tool, surfaced so QML can render the picture INLINE (the
    # whole point of the tool) and, on failure, an honest error line in its place
    # (docs/DESIGN.md §10). ONE data contract with QML: `imageFetchResult` carries
    # a single JSON entry — {ok:true, url, path, alt, w, h} for a fetched image,
    # or {ok:false, url, error} for any failure — which QML parses and appends to
    # the turn's image list.
    imageFetchStarted = Signal(str)         # url
    imageFetchResult = Signal(str)          # one JSON entry (the contract above)

    # The video tool, the same shape one step along: `videoResult` carries a
    # single JSON entry — {ok:true, url, src, title, alt, w, h, duration, poster}
    # for a resolved video, or {ok:false, url, error} — which QML appends to the
    # turn's video list and draws as a card. `src` is a URL the MediaPlayer
    # streams; nothing is on disk but the poster frame.
    videoStarted = Signal(str)              # url — resolving
    videoResult = Signal(str)               # one JSON entry (the contract above)

    # A run_bash/run_python program's output AS IT RUNS (tools/sandbox-exec.py
    # `stream: true`). One chunk per signal, already decoded; QML keeps a
    # bounded tail of it on the row so a thirty-second command is not a still
    # window (docs/DESIGN.md §10 — the wait is shown, and here it is shown with
    # the work in it).
    execOutput = Signal(str)                # one chunk of live output
    execStarted = Signal(str)               # the language, as a heading
    execFinished = Signal()                 # that program stopped running

    # A GENERATION, AS IT RUNS. A render is minutes long and until now the chat
    # showed one motionless "making a picture…" for all of it, which reads as
    # stalled [his, 2026-08-24]. painter's generator prints `::progress FRAC
    # LABEL` for us (`--progress`), and QML draws it as a small bar under the
    # tool disclosure — the same place the reasoning and the file lines live.
    genProgress = Signal(str, float)        # label, 0..1
    genFinished = Signal(bool)              # …and that render stopped (ok?)

    # The player tool's result, as JSON — for a harness to read what one call
    # actually produced without a bus of its own.
    playerToolDone = Signal(str)

    # Live model stats, drawn as readouts in the status area. `contextMax` is the
    # selected model's real context ceiling read from ollama's /api/show (the
    # model's own `<arch>.context_length`, not a filename guess); `tokensPerSec`
    # is the generation rate — a running estimate while a reply streams, settled
    # to ollama's exact eval_count/eval_duration on the done frame.
    contextMaxChanged = Signal()
    tokensPerSecChanged = Signal()
    contextUsedChanged = Signal()   # tokens in play as of the last turn (prompt+gen)
    memoriesChanged = Signal()      # how many durable memories it is carrying
    capabilitiesChanged = Signal()  # the model's native capabilities (/api/show)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._models = []
        self._last_model = self._load_last_model()  # pre-select this next launch
        self._suggested = self._load_suggested()    # agent-recommended, ranked first
        self._suggested_count = 0                   # how many of _models are suggested
        self._busy = False
        # The memory arbiter (home/srvs/ai-warden.nix). A 24 GiB model landing
        # on top of a painter render is what livelocks the box, so a turn asks
        # for room before it is sent. Fail-open by construction: no warden, no
        # gate. See apps/pylib/warden.py.
        self._warden = Warden(self)
        # A typed video ends the turn when it lands — both routes (resolved or
        # failed) come home through `videoResult`.
        self.videoResult.connect(lambda _j: self._typed_video_done())
        self._reply = None       # the in-flight chat QNetworkReply, if any
        self._buf = b""          # partial NDJSON line carried between reads
        self._think_tokens = 0   # reasoning tokens seen this turn (one per delta)
        self._model = ""         # the model for the current turn
        self._messages = []      # the growing message list across a tool loop
        self._acc_content = ""   # assistant content accumulated in this sub-turn
        self._done_reason = ""   # ollama's reason the last frame was the last
        self._pending_vision = []  # local images view_image is handing the model
        self._images_shown = set()
        self._paths_shown = set()  # …and every LOCAL file already drawn, by path
        self._made_this_turn = {}  # kind -> the path it already generated
        self._image_entries = {}   # url -> the entry we already drew, this turn
        self._row_urls = set()     # …and which of them are on the CURRENT bubble
        self._md_images = {"n": 0}
        self._md_videos = {"n": 0}
        self._videos_shown = set()
        self._tool_calls = []    # tool calls accumulated in this sub-turn
        self._rounds = 0         # tool rounds taken this turn (MAX_TOOL_ROUNDS cap)
        self._no_tools = False   # the wrap-up round: answer, do not call tools
        self._squeezed = False   # this turn wrote its answer UNDER DURESS — see
                                 # `_truncation_reason`
        self._extra_tools = set()  # tools `get_tools` attached THIS turn
        self._prior = []         # the LAST finished turn's messages, tool rounds
                                 # and all — see `_carry` (working memory)
        self._prior_users = []   # the RAW prompts behind it, for the match
        self._pending_users = []  # …of the turn in flight, promoted when it ends
        self._synthetic = set()   # indices in _messages the harness wrote, not
                                  # him — kept out of the memory (continueReply)
        self._partial_prefix = ""  # the answer so far, when this turn continues one
        self._house_seen = set()  # guides already named this conversation
        self._max_results = RESEARCH_MAX  # per-search source cap for this turn (set in send)
        self._procs = []         # live file-tool QProcesses, so none is GC'd mid-run
        self._gen_procs = []     # the generator ones among them — Stop kills these
        self._memories = []      # oracle's own durable memories, injected each turn
        self._prompt_choice, self._custom_prompt = self._load_prompt_config()
        self._ctx_max = 0        # the window actually in force (0 = unknown)
        self._ctx_train = 0      # …and the model's own trained ceiling
        self._ctx_model = ""     # which model those two were read for
        self._num_ctx = CHAT_NUM_CTX   # the window THIS turn asks ollama for
        self._ctx_fit = CtxFit(self)   # what this machine can actually give
        self._jobs = None        # the Jobs object, set in main(); the job tools
                                 # and the tray read the same one
        self._model_sizes = {}   # model -> weights on disk, from /api/tags
        self._loaded_ctx = {}    # model -> the window it is LOADED in (/api/ps)
        self._caps = []          # selected model's native capabilities (/api/show)
        self._tps = 0.0          # generation rate of the current/last reply
        self._resp_t0 = 0.0      # monotonic start of the reply's content stream
        self._resp_tokens = 0    # content frames seen this reply (≈ tokens)
        self._ctx_used = 0       # tokens the context held at the last turn (prompt+gen)

    # ---- model list ----

    @Property("QStringList", notify=modelsChanged)
    def models(self):
        return self._models

    @Property(str, notify=lastModelChanged)
    def lastModel(self):
        return self._last_model

    @Slot(str, str, result=str)
    def replyRuns(self, body, imagesJson):
        """Split a reply's markdown into the runs an inline bubble renders.

        The model places a picture inline by writing `![alt](url)` where it
        wants it in the prose. QML lays the reply out as a flow of runs rather
        than one TextEdit so the picture can sit AT that spot — but a TextEdit
        would draw the URL at its raw pixel size and fetch it on render, so the
        split happens here, where the row's fetched images are known.

        Returns a JSON object:
          {"runs":[{t:"text",md}|{t:"img",url,path,alt,w,h}|{t:"bad",url,error}],
           "leftovers":[...]}
        - a `text` run is the markdown between two images, with any image it
          could NOT place (not fetched this turn) demoted to a plain link so
          nothing is hidden (docs/DESIGN.md §10) and nothing is auto-fetched.
        - an `img` run is a fetched local file to draw in place, alpha intact
          (PNG stays PNG — no flatten, so transparency survives).
        - a `bad` run is a fetch that failed, named honestly where the picture
          was meant to be.
        - `leftovers` are the row's images the reply never referenced inline,
          for the trailing gallery — a fetched picture must still be SEEN even
          when the model did not tie it to a word.
        """
        try:
            images = json.loads(imagesJson) if imagesJson else []
        except (ValueError, TypeError):
            images = []
        if not isinstance(images, list):
            images = []
        by_ok, by_bad = {}, {}
        for e in images:
            if not isinstance(e, dict):
                continue
            u = str(e.get("url") or "")
            if not u:
                continue
            if e.get("ok") and e.get("path"):
                by_ok.setdefault(u, e)
            else:
                by_bad.setdefault(u, e)

        body = body or ""
        runs, text_parts = [], []
        referenced = set()
        last = 0

        def flush():
            md = "".join(text_parts)
            if md.strip():
                runs.append({"t": "text", "md": md})
                del text_parts[:]

        for m in re.finditer(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+[^)\s]*)?\)",
                             body):
            alt = m.group(1).strip()
            url = m.group(2).rstrip(")")
            referenced.add(url)
            text_parts.append(body[last:m.start()])
            entry = by_ok.get(url)
            if entry:
                flush()
                runs.append({"t": "img", "url": url, "path": entry["path"],
                             "alt": alt or entry.get("alt", ""),
                             "w": int(entry.get("w") or 0),
                             "h": int(entry.get("h") or 0)})
            else:
                bad = by_bad.get(url)
                if bad:
                    flush()
                    runs.append({"t": "bad", "url": url,
                                 "error": bad.get("error", "could not display")})
                else:
                    # Not fetched: keep it a plain link. The URL is still there
                    # and clickable — just not auto-fetched or upscaled.
                    text_parts.append("[%s](%s)" % (alt, url))
            last = m.end()
        text_parts.append(body[last:])
        flush()

        leftovers = [e for e in images
                     if isinstance(e, dict) and str(e.get("url") or "")
                     not in referenced]
        return json.dumps({"runs": runs, "leftovers": leftovers},
                          ensure_ascii=False)

    @Property(int, notify=modelsChanged)
    def suggestedCount(self):
        """How many leading entries of `models` are agent-suggested — so the
        dropdown can rule off the suggested group from the rest (§7.2)."""
        return self._suggested_count

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(int, constant=True)
    def autoContinueMax(self):
        """How many times one prompt may be carried on without him."""
        return AUTO_CONTINUE_MAX

    def _set_busy(self, v):
        if v != self._busy:
            self._busy = v
            # The turn is over however it ended — hand the memory back so
            # painter can have it. Every exit (done, error, cancel) is here.
            if not v:
                self._warden.done("ollama")
            self.busyChanged.emit()

    # ---- the last-picked model, and the agent-suggested ranking ----

    @staticmethod
    def _load_last_model():
        try:
            return LAST_MODEL_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @staticmethod
    def _load_suggested():
        """The agent-suggested model names, de-duped, order preserved. Missing
        or malformed file (or anything but a JSON list of strings) → none."""
        try:
            data = json.loads(SUGGESTED_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out, seen = [], set()
        for x in data:
            if isinstance(x, str) and x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def _order(self, names):
        """Agent-suggested models the daemon actually has come first, in the
        order they were suggested; everything else follows alphabetically. Sets
        `_suggested_count` as a side effect (the size of that leading group)."""
        present = set(names)
        top = [m for m in self._suggested if m in present]
        seen = set(top)
        rest = sorted((n for n in names if n not in seen), key=str.lower)
        self._suggested_count = len(top)
        return top + rest

    # ---- how loud a clip plays, once, for all of them ---------------------

    @Slot(result=float)
    def videoVolume(self):
        """The remembered clip volume, 0..1 (1 the first time)."""
        try:
            v = float(VIDEO_VOLUME_PATH.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 1.0
        return max(0.0, min(1.0, v))

    @Slot(float)
    def rememberVideoVolume(self, v):
        """Persist it. A write failure is swallowed — the setting is a
        convenience and the session it was set in already has it."""
        try:
            v = max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            VIDEO_VOLUME_PATH.write_text("%.4f\n" % v, encoding="utf-8")
        except OSError:
            pass

    @Slot(str)
    def rememberModel(self, name):
        """Persist `name` as the model to pre-select next launch (a pick or a
        send). No-op when unchanged; a write failure is swallowed — the setting
        is a convenience, not load-bearing."""
        name = (name or "").strip()
        if not name or name == self._last_model:
            return
        self._last_model = name
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            LAST_MODEL_PATH.write_text(name + "\n", encoding="utf-8")
        except OSError:
            pass
        self.lastModelChanged.emit()

    # ---- the base system prompt (a preset, or his own custom text) ----

    @staticmethod
    def _load_prompt_config():
        """`(choice, custom_text)` from SYSPROMPT_PATH. A missing/malformed file,
        or a choice that names no known preset and is not "custom", falls back to
        the built-in default with empty custom text — never an error."""
        try:
            data = json.loads(SYSPROMPT_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ("default", "")
        if not isinstance(data, dict):
            return ("default", "")
        choice = data.get("choice", "default")
        custom = data.get("custom", "")
        if not isinstance(custom, str):
            custom = ""
        if choice != "custom" and choice not in PROMPT_PRESET_IDS:
            choice = "default"
        return (choice, custom)

    def _save_prompt_config(self):
        """Persist the current choice + custom text. Swallowed on failure — the
        setting is a convenience, not load-bearing (same as `rememberModel`)."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            SYSPROMPT_PATH.write_text(
                json.dumps({"choice": self._prompt_choice,
                            "custom": self._custom_prompt}),
                encoding="utf-8")
        except OSError:
            pass

    @Property("QVariantList", constant=True)
    def promptPresets(self):
        """The built-in presets (id/label/text) for the picker; `custom` is
        offered by QML alongside these."""
        return [dict(p) for p in PROMPT_PRESETS]

    @Property(str, notify=promptChanged)
    def promptChoice(self):
        return self._prompt_choice

    @Property(str, notify=promptChanged)
    def customPrompt(self):
        return self._custom_prompt

    @Slot(str)
    def setPromptChoice(self, choice):
        """Select which base prompt is active (a preset id, or "custom")."""
        choice = (choice or "").strip()
        if choice != "custom" and choice not in PROMPT_PRESET_IDS:
            return
        if choice == self._prompt_choice:
            return
        self._prompt_choice = choice
        self._save_prompt_config()
        self.promptChanged.emit()

    @Slot(str)
    def setCustomPrompt(self, text):
        """Persist his own custom base text (and leave the choice as-is; QML
        selects "custom" when he wants it applied)."""
        text = text or ""
        if text == self._custom_prompt:
            return
        self._custom_prompt = text
        self._save_prompt_config()
        self.promptChanged.emit()

    def _base_prompt(self):
        """The active base text prepended to every turn's system prompt — the
        custom text when "custom" is chosen, else the chosen preset's text, else
        empty (the default). Empty contributes nothing (see `_system_prompt`)."""
        if self._prompt_choice == "custom":
            return self._custom_prompt.strip()
        for p in PROMPT_PRESETS:
            if p["id"] == self._prompt_choice:
                return p["text"].strip()
        return ""

    # ---- model stats (context ceiling + generation rate) ----

    @Property(int, notify=contextMaxChanged)
    def contextMax(self):
        """The window ACTUALLY IN FORCE for the selected model, in tokens.

        Not the model's trained ceiling, which is what this said until
        2026-08-23 and which nothing on this machine was ever going to give him
        — qwen3.6 reads 262144 there while every turn ran in 32768. It is
        ollama's own `context_length` from `/api/ps` once the model is loaded
        (measured), and until then the window the next turn will ask for
        (`CtxFit`). 0 while unknown."""
        return self._ctx_max

    @Property(int, notify=contextMaxChanged)
    def contextTrained(self):
        """The model's own trained ceiling — the number `contextMax` used to
        show. Drawn dim beside it, so nothing is hidden: it is what he COULD
        have with more memory, not what he has."""
        return self._ctx_train

    @Property("QStringList", notify=capabilitiesChanged)
    def capabilities(self):
        """The selected model's native capabilities as ollama reports them
        (/api/show `capabilities`, e.g. vision/tools/thinking/audio) — the real
        list for the selected model, empty while unknown. Drawn as indicator
        chips beside the context bar; the baseline `completion` is filtered out
        as noise (every chat model has it)."""
        return self._caps

    @Property(float, notify=tokensPerSecChanged)
    def tokensPerSec(self):
        """Generation rate of the current/last reply, 0 before one has run."""
        return self._tps

    @Property(int, notify=contextUsedChanged)
    def contextUsed(self):
        """Tokens the model's context held at the last turn (its own
        prompt_eval_count + eval_count), 0 before one has run — the numerator of
        the context-fill readout against contextMax."""
        return self._ctx_used

    def _set_ctx_used(self, v):
        v = int(v) if v and v > 0 else 0
        if v != self._ctx_used:
            self._ctx_used = v
            self.contextUsedChanged.emit()

    def _set_tps(self, v):
        v = float(v) if v and v > 0 else 0.0
        if abs(v - self._tps) > 1e-6:
            self._tps = v
            self.tokensPerSecChanged.emit()

    def _set_window(self, model):
        """Recompute the window in force for `model`, and publish it.

        Ground truth first: if ollama has the model LOADED, `/api/ps` says the
        window it was loaded in and that is the number, whatever this app would
        have asked for. Otherwise it is what the next turn WILL ask for — the
        `CtxFit` number, capped by the model's trained ceiling.
        """
        model = (model or "").strip()
        fit = self._ctx_fit.numCtx(
            model, trained=self._ctx_train,
            loaded=model in self._loaded_ctx,
            weights=self._model_sizes.get(model, 0))
        live = int(self._loaded_ctx.get(model, 0))
        # A LOADED MODEL KEEPS THE WINDOW IT WAS LOADED IN. Asking for a
        # different one costs a full reload — 24 GB of weights off the disk,
        # mid-conversation — so a newly measured fit applies at the next load
        # (ollama drops the model after its keep_alive), never under him.
        self._num_ctx = live if live > 0 else fit
        eff = live if live > 0 else fit
        if not model:
            eff = 0
        if eff != self._ctx_max:
            self._ctx_max = eff
            self.contextMaxChanged.emit()

    @Slot(str)
    def notePs(self, ps_json):
        """What `/api/ps` last said, handed over by `Backend`'s 3s poll.

        Two things come out of it: the window each loaded model is ACTUALLY
        running in (the stat line's ground truth), and the chance to measure
        that model's KV cost once, which is what lets `CtxFit` size the next
        one. Never its own poll — the daemon is already being asked.
        """
        try:
            obj = json.loads(ps_json or "{}")
            models = obj.get("models") or []
        except (ValueError, TypeError):
            return
        seen = {}
        for m in models:
            name, ctx = m.get("name"), m.get("context_length")
            if name and isinstance(ctx, (int, float)) and ctx > 0:
                seen[str(name)] = int(ctx)
                self._ctx_fit.calibrate(str(name), int(ctx))
        if seen != self._loaded_ctx:
            self._loaded_ctx = seen
            self._set_window(self._ctx_model)

    @Slot(str)
    def refreshModelInfo(self, model):
        """Read the model's trained ceiling from ollama's /api/show —
        `<arch>.context_length` in `model_info`, the model's own window, not a
        filename guess (docs/DESIGN.md §10: a shown number is a true one) — and
        recompute the window actually in force from it (`_set_window`).
        Async; leaves the stats at 0/unknown on any failure rather than
        inventing a value."""
        model = (model or "").strip()
        if not model:
            self._ctx_model = ""
            self._ctx_train = 0
            if self._ctx_max:
                self._ctx_max = 0
                self.contextMaxChanged.emit()
            if self._caps:
                self._caps = []
                self.capabilitiesChanged.emit()
            return
        if model == self._ctx_model and self._ctx_train:
            self._set_window(model)         # memory moves; the ceiling does not
            return
        self._ctx_model = model
        self._set_window(model)             # a first answer, before /api/show
        req = QNetworkRequest(QUrl(OLLAMA + "/api/show"))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        reply = self._nam.post(req, json.dumps({"model": model}).encode("utf-8"))

        def done():
            ctx = 0
            caps = []
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    obj = json.loads(bytes(reply.readAll().data()).decode(
                        "utf-8", "replace") or "{}")
                    ctx = self._parse_context_length(obj)
                    caps = self._parse_capabilities(obj)
            except (ValueError, RuntimeError):
                ctx, caps = 0, []
            reply.deleteLater()
            if model != self._ctx_model:
                return                      # a newer selection superseded this
            if ctx != self._ctx_train:
                self._ctx_train = ctx
                self.contextMaxChanged.emit()
            self._set_window(model)
            if caps != self._caps:
                self._caps = caps
                self.capabilitiesChanged.emit()

        reply.finished.connect(done)

    @staticmethod
    def _parse_capabilities(show):
        """The model's native capabilities from an /api/show reply: ollama's own
        top-level `capabilities` list (vision/tools/thinking/audio/insert/…),
        with the baseline `completion` dropped as noise. Order preserved; [] when
        the field is absent or malformed (never a guess)."""
        caps = show.get("capabilities")
        if not isinstance(caps, list):
            return []
        return [str(c) for c in caps
                if isinstance(c, str) and c and c != "completion"]

    @staticmethod
    def _parse_context_length(show):
        """The context ceiling from an /api/show reply: the architecture's own
        `<arch>.context_length` in `model_info`. Falls back to any *.context_length
        key, then 0 (unknown — never a guess)."""
        info = show.get("model_info") or {}
        if not isinstance(info, dict):
            return 0
        arch = ""
        if isinstance(show.get("details"), dict):
            arch = show["details"].get("family") or ""
        arch = info.get("general.architecture") or arch
        if arch:
            v = info.get(str(arch) + ".context_length")
            if isinstance(v, (int, float)) and v > 0:
                return int(v)
        for k, v in info.items():
            if k.endswith(".context_length") and isinstance(v, (int, float)) and v > 0:
                return int(v)
        return 0

    @Slot()
    def refreshModels(self):
        req = QNetworkRequest(QUrl(OLLAMA + "/api/tags"))
        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._on_tags(reply))

    def _on_tags(self, reply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.modelsError.emit(reply.errorString())
                return
            data = bytes(reply.readAll().data())
            obj = json.loads(data or b"{}")
            # Re-read the suggestions here (not just at startup) so an agent that
            # writes suggested.json while oracle runs is honoured on the next
            # daemon poll, with no relaunch.
            self._suggested = self._load_suggested()
            for m in obj.get("models", []):
                if m.get("name") and isinstance(m.get("size"), (int, float)):
                    self._model_sizes[str(m["name"])] = int(m["size"])
            names = self._order([m.get("name", "") for m in obj.get("models", [])
                                 if m.get("name")])
            if names != self._models:
                self._models = names
                self.modelsChanged.emit()
        except (ValueError, TypeError) as e:
            self.modelsError.emit(str(e))
        finally:
            reply.deleteLater()

    # ---- one streamed chat turn ----

    @Slot(str, str, str)
    @Slot(str, str, str, str)
    def send(self, model, prompt, history_json, attachments_json=""):
        """`history_json` is the CURRENT chat's prior turns (QML's chatLog,
        user+assistant, before this one), so the model sees the whole
        conversation so far rather than just the latest prompt — the tool-call
        loop below still only accumulates within THIS turn on top of it.

        `attachments_json` is the files he dragged onto the window this turn
        (`[{name, path}]`): their text is read LOCALLY (they are his own dropped
        files, not sandbox paths) and inlined into THIS user message as context,
        so the model receives them. Capped and binary-aware (see
        `_read_attachments`)."""
        if not model or not prompt.strip():
            return
        self.cancel()          # one turn at a time
        self._model = model
        # Scale research depth to the ask: a simple factual question gets a small
        # source cap and is told not to fan out; a broad one may go wide. Judged
        # on the PROMPT, before attachments are inlined — a dropped file's bulk
        # must not read as a "broad" question and fan the web search wide.
        budget = self._research_budget(prompt)
        self._max_results = budget["max_results"]
        # Split the dropped files: images go to the model as native vision blocks
        # (if the model supports vision), everything else is inlined as text.
        items = self._parse_attachment_items(attachments_json)
        image_items, file_items = [], []
        for it in items:
            (image_items if self._sniff_image(it["path"]) else file_items).append(it)
        # Trust the capability list only when it was read for THIS model (the
        # selection triggers the /api/show that fills it); otherwise treat vision
        # as unknown, which falls back to the honest "not sent" note below.
        vision = self._ctx_model == model and "vision" in (self._caps or [])
        attach_block = self._read_attachments(file_items)
        images_b64, img_note = self._read_image_attachments(image_items, vision)
        # Beyond the bounded inline text, stage each dropped file INTO the file-
        # tool sandbox so the model can read the FULL file and edit it in place.
        staged, stage_errs = (self._stage_attachments(file_items)
                              if file_items else ([], []))
        stage_note = self._stage_note(staged, stage_errs)
        content = prompt
        if attach_block:
            content += "\n\n" + attach_block
        if stage_note:
            content += "\n\n" + stage_note
        if img_note:
            content += "\n\n" + img_note
        # HIS SHORTHAND, parsed here rather than by the model (genshort.py):
        # "anima. 2:3 x1 1girl, solo" is a job with numbers in it, and a local
        # model asked to infer them gets the aspect backwards and rewrites his
        # tag list. The parse is conservative — a message that does not open
        # with a model or mode word produces nothing at all.
        gen = genshort.parse(prompt, [it["path"] for it in image_items])
        if gen:
            content += "\n\n" + genshort.hint_for(gen)
        user_msg = {"role": "user", "content": content}
        if images_b64:                     # ollama /api/chat: base64 on the message
            user_msg["images"] = images_b64
        # WHAT IT DID LAST TURN COMES WITH IT. `_carry` returns the previous
        # turn's whole message list — tool calls and results included — when
        # this is the next turn of the same conversation, so the agent starts
        # where it left off instead of blind (TOOL_CARRY_CHARS).
        hist = self._parse_history(history_json)
        carried = self._carry(hist)
        if carried is None:
            self._house_seen = set()      # a different chat: name the guides again
        # What the NEXT turn's history will look like if this one lands: the
        # prompts as QML holds them, before attachments and notes are inlined.
        self._pending_users = self._user_texts(hist) + [prompt]
        self._synthetic = set()
        self._partial_prefix = ""
        self._messages = ([{"role": "system",
                            "content": self._system_prompt(budget["guidance"])}]
                          + (carried if carried is not None else hist)
                          + [user_msg])
        self._think_tokens = 0
        self._rounds = 0
        self._images_shown = set()   # every image URL already fetched this turn
        self._paths_shown = set()    # …and every LOCAL file already drawn, by path
        self._made_this_turn = {}    # what this turn has already GENERATED, by kind
        self._image_entries = {}     # …and the entry each one produced, to redraw
        self._row_urls = set()       # what is already on the bubble being written
        self._md_images = {"n": 0}   # typed-markdown images still downloading
        self._md_videos = {"n": 0}   # …and typed videos still resolving
        self._videos_shown = set()   # every video URL already drawn this turn
        self._pending_vision = []    # local images view_image must hand the model
        self._no_tools = False       # not a wrap-up round
        self._squeezed = False       # …and nothing has squeezed it yet
        self._extra_tools = set()    # a fresh turn attaches its own tools
        if gen:
            # The generator is not a CORE tool, so a turn that is plainly a
            # generation attaches it itself rather than spending a get_tools
            # round on a job whose arguments are already parsed.
            self._extra_tools.add(gen["tool"])
        self._resp_t0 = 0.0
        self._resp_tokens = 0
        self._set_tps(0.0)
        self.refreshModelInfo(model)   # keep the context stat matched to the turn
        self._set_busy(True)
        self.replyStarted.emit()

        # ASK FOR THE MEMORY FIRST. Loading a 24 GiB model beside a ComfyUI
        # render is not a slow turn, it is a frozen desktop — so the warden
        # either frees painter's weights (its own toast says so) or refuses,
        # and a refusal is DRAWN rather than swallowed (docs/DESIGN.md §10).
        # Anything wrong with the warden itself calls back ok, always.
        def _go(ok, reason):
            if not ok:
                self._set_busy(False)
                self.replyError.emit(reason)
                return
            self._post_chat()

        self._warden.reserve("ollama", model=model, cb=_go)

    #: What `continueReply` says to a model whose answer stopped mid-sentence.
    #: A user turn, not an assistant prefix: ollama will happily generate from a
    #: trailing assistant message, but no model is reliable about NOT starting
    #: over when asked that way, and the partial is right there above it.
    CONTINUE_PROMPT = (
        "Your previous message was cut off mid-way — you ran out of room, "
        "either tokens or context. Carry on from exactly where it stopped — "
        "continue the very next character, mid-sentence and mid-word if that is "
        "where it ended. Do not repeat any of it, do not summarise it, do not "
        "start over, and do not add a preamble like \"continuing\".")

    #: What the wrap-up round says to a model that has used every tool round.
    #: A user turn for the same reason CONTINUE_PROMPT is one.
    TOOL_CAP_PROMPT = (
        "You have used all the tool calls available for this turn, so there "
        "are no tools on this message. Answer him now, in words, with what you "
        "have already found — say what you learned and what you could not "
        "establish. Do not describe another command you would like to run.")

    #: What `continueReply` says to a model whose answer FINISHED and which he
    #: has asked to keep going anyway — the plain "go on" any reply can take,
    #: not a resume. Mid-word continuation would be wrong here: the sentence
    #: ended, so this one asks for what comes NEXT.
    EXTEND_PROMPT = (
        "Carry on from where your previous message ended: say what comes next "
        "— the part you did not get to, in more depth, or the next step. Do "
        "not repeat or summarise what you already said, and do not open with a "
        "preamble like \"continuing\" or \"sure\".")

    #: What an AUTO-CONTINUE says: the model announced its next step instead of
    #: taking it, so it is told to take it. A user turn, like the others.
    PROCEED_PROMPT = (
        "Yes — go ahead and do it, now, with your tools. That was already what "
        "he asked for, so do not ask again and do not restate the plan: act, "
        "then tell him what happened. If it turns out you cannot, say why.")

    #: What it says when the previous turn produced NO words at all (it spent
    #: the turn on tools and never wrote). There is nothing to carry on from.
    ANSWER_PROMPT = (
        "Your previous turn used its tools but never wrote an answer. Answer "
        "now, in words, with what you found.")

    @Slot(str, str, str)
    @Slot(str, str, str, str)
    def continueReply(self, model, history_json, partial, mode="resume"):
        """Carry a reply on, into the SAME message.

        `history_json` is every turn BEFORE this one; `partial` is what that
        turn said. The model is handed both plus one of three instructions and
        QML streams the answer onto the end of the row it already has — so a
        continued answer stays ONE answer, not two bubbles that have to be read
        together [his, 2026-08-22].

        `mode` picks the instruction: `resume` for an answer that stopped
        mid-sentence (the length ceiling, or he pressed stop), `extend` for a
        finished answer he wants more of [his, 2026-08-23 — continue is offered
        on any reply, not only a truncated one], and either one with an empty
        `partial` becomes ANSWER_PROMPT, the turn that spent itself on tools
        and never wrote.

        Everything else is `send`'s machinery unchanged: same tools, same warden
        reservation, same streaming path.
        """
        if not model:
            return
        self.cancel()
        self._model = model
        budget = self._research_budget(partial[-2000:])
        self._max_results = budget["max_results"]
        if not partial.strip():
            instruction = self.ANSWER_PROMPT
        elif mode == "proceed":
            instruction = self.PROCEED_PROMPT
        elif mode == "extend":
            instruction = self.EXTEND_PROMPT
        else:
            instruction = self.CONTINUE_PROMPT
        prior = ([{"role": "assistant", "content": partial}]
                 if partial.strip() else [])
        # Same working memory as `send` — and it matters more here: `continue`
        # is pressed exactly when a turn ran out of room mid-job, and rebuilding
        # from the chat log alone threw away everything that turn had read.
        hist = self._parse_history(history_json)
        carried = self._carry(hist)
        # `partial` IS the last answer, handed over by QML — so if the memory
        # ends with that same answer, the memory's copy goes, not this one.
        # Otherwise the model reads its own last words twice in a row and
        # continues from the wrong end of them.
        if carried and partial.strip():
            last = carried[-1]
            body = str(last.get("content") or "").strip()
            if (last.get("role") == "assistant" and not last.get("tool_calls")
                    and body and partial.strip().startswith(body[:200])):
                carried = carried[:-1]
        # The instruction below is the harness talking, not him: the chat log
        # will not have it next turn, so the fingerprint stays the prompts.
        self._pending_users = (self._prior_users if carried is not None
                               else self._user_texts(hist))
        self._messages = ([{"role": "system",
                            "content": self._system_prompt(budget["guidance"])}]
                          + (carried if carried is not None else hist)
                          + prior
                          + [{"role": "user", "content": instruction}])
        # The partial answer and the instruction are the HARNESS talking, and
        # neither belongs in what the next turn remembers: the instruction was
        # never his, and the partial comes back as part of the finished answer
        # (`_partial_prefix`). Their indices are stable — tool rounds only ever
        # append past them.
        self._synthetic = set(range(len(self._messages) - len(prior) - 1,
                                    len(self._messages)))
        self._partial_prefix = partial if partial.strip() else ""
        self._think_tokens = 0
        self._rounds = 0
        self._images_shown = set()
        self._paths_shown = set()
        self._made_this_turn = {}
        self._image_entries = {}
        self._row_urls = set()
        self._md_images = {"n": 0}
        self._md_videos = {"n": 0}
        self._videos_shown = set()
        self._pending_vision = []
        self._no_tools = False
        self._squeezed = False
        self._extra_tools = set()
        self._resp_t0 = 0.0
        self._resp_tokens = 0
        self._set_tps(0.0)
        self.refreshModelInfo(model)
        self._set_busy(True)
        self.replyStarted.emit()

        def _go(ok, reason):
            if not ok:
                self._set_busy(False)
                self.replyError.emit(reason)
                return
            self._post_chat()

        self._warden.reserve("ollama", model=model, cb=_go)

    @Slot(str, result=bool)
    def looksUnfinished(self, text):
        """Did this answer ANNOUNCE its next step instead of taking it?

        True means the app carries the turn on by itself rather than making him
        press `continue` (QML counts those, AUTO_CONTINUE_MAX of them). Only the
        TAIL is read — the last couple of sentences are where a model says what
        it is about to do — so a long answer that merely mentions a plan in
        passing and then finishes the work does not match.

        AN ANSWER THAT ENDS IN A QUESTION IS WAITING ON HIM, whatever else the
        tail says. It is his turn, and pressing `continue` on his behalf answers
        his own question with `proceed` — which is how "hello" became five tool
        rounds ending in a track queued for him [his, 2026-08-23]. The model
        announcing its next step and then asking anyway costs him one press;
        answering for him costs him actions he never asked for.
        """
        tail = (text or "")[-400:].lower()
        if not tail.strip():
            return False
        if tail.rstrip().endswith("?"):
            return False
        return any(re.search(p, tail) for p in UNFINISHED_PATTERNS)

    @Slot(str, result="QVariant")
    def localFileInfo(self, url):
        """Resolve a dropped file URL to {name, path}. QUrl does the decode, in
        Python, once — never `decodeURI` in QML, which mangles `#`/`?` in a
        uri-list (docs/DESIGN.md §13). Returns {} for a non-local URL."""
        p = QUrl(url).toLocalFile()
        if not p:
            return {}
        return {"name": os.path.basename(p) or p, "path": p}

    @staticmethod
    def _parse_attachment_items(attachments_json):
        """Validate the dragged-file list (`[{name, path}]`) QML sends into a
        clean list of `{name, path}` dicts, dropping anything malformed or
        path-less. The single place the raw JSON boundary is parsed."""
        try:
            items = json.loads(attachments_json or "[]")
        except ValueError:
            return []
        if not isinstance(items, list):
            return []
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            path = str(it.get("path", ""))
            if not path:
                continue
            name = str(it.get("name", "")) or os.path.basename(path) or "file"
            out.append({"name": name, "path": path})
        return out

    @staticmethod
    def _sniff_image(path):
        """The image media-type of a file from its MAGIC BYTES (never the
        extension — his rule for the attachment path), or "" if it is not one of
        the raster image types a vision model accepts (png/jpeg/gif/webp)."""
        try:
            with open(path, "rb") as fh:
                head = fh.read(16)
        except OSError:
            return ""
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if head[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
        return ""

    @classmethod
    def _read_image_attachments(cls, image_items, vision):
        """Turn dropped IMAGE files into what the turn needs.

        For a **vision-capable** model: base64-encode each (bounded by
        ATTACH_IMAGE_MAX) for ollama's `images` message field, plus a short text
        note naming them so the visible/saved turn acknowledges them. For a model
        with **no vision support**: send NO image bytes and return a text note
        that images were attached but this model cannot see them — never silently
        dropped (docs/DESIGN.md §10 affordance honesty). Returns
        `(base64_list, note)`; an oversized or unreadable image is NAMED in the
        note either way."""
        if not image_items:
            return [], ""
        b64, ok_names, skipped = [], [], []
        for it in image_items:
            path, name = it["path"], it["name"]
            if not vision:
                continue               # bytes are read only for a vision model
            try:
                size = os.path.getsize(path)
                if size > ATTACH_IMAGE_MAX:
                    skipped.append("%s (%d MB, over the %d MB image limit)"
                                   % (name, size // (1024 * 1024),
                                      ATTACH_IMAGE_MAX // (1024 * 1024)))
                    continue
                with open(path, "rb") as fh:
                    b64.append(base64.b64encode(fh.read()).decode("ascii"))
                ok_names.append(name)
            except OSError as e:
                skipped.append("%s (could not read: %s)" % (name, e.strerror))
        # THE PATH IS PART OF THE NOTE, whether the model can see the picture
        # or not: an attachment is also the thing make_image edits and the frame
        # make_video animates from, and neither needs vision. Without it the
        # model has a picture it cannot name to a tool.
        where = "\n".join("  %s — %s" % (it["name"], it["path"])
                           for it in image_items)
        if not vision:
            names = ", ".join(it["name"] for it in image_items)
            return [], ("[attached image(s): %s — the selected model has no "
                        "vision support, so they were not sent, and you have "
                        "not seen them. Pick a vision-capable model to look. "
                        "make_image and make_video do not need vision and can "
                        "still use them, at these paths:\n%s]" % (names, where))
        parts = []
        if ok_names:
            parts.append("[attached image(s), which you can see above, and "
                         "which make_image/make_video can use at these "
                         "paths:\n%s]" % where)
        if skipped:
            parts.append("[image(s) not sent: %s]" % "; ".join(skipped))
        return b64, "\n".join(parts)

    @staticmethod
    def _read_attachments(items):
        """Turn the dragged TEXT files (`[{name, path}]`, images already routed
        away) into one context block inlined into the user message, or "" if
        there are none.

        Read LOCALLY (his own dropped files), text only, and bounded: each file
        is capped at ATTACH_FILE_MAX and the whole turn at ATTACH_TOTAL_MAX, with
        a truncation note when a file is clipped. A binary file (undecodable, or
        a NUL byte) or one that cannot be read is NAMED with the reason rather
        than dumped (docs/DESIGN.md §10 — the attachment is acknowledged, never
        silently dropped; §5 his context-budget rule — never blow the window)."""
        if not items:
            return ""
        blocks, total = [], 0
        for it in items:
            if not isinstance(it, dict):
                continue
            path = str(it.get("path", ""))
            name = str(it.get("name", "")) or os.path.basename(path) or "file"
            if not path:
                continue
            note, body = "", ""
            try:
                with open(path, "rb") as fh:
                    raw = fh.read(ATTACH_FILE_MAX + 1)
                if b"\x00" in raw:
                    note = "binary file, not inlined"
                else:
                    try:
                        body = raw[:ATTACH_FILE_MAX].decode("utf-8")
                    except UnicodeDecodeError:
                        note = "binary file, not inlined"
                    else:
                        if len(raw) > ATTACH_FILE_MAX:
                            note = "truncated to %d KB" % (ATTACH_FILE_MAX // 1024)
            except OSError as e:
                note = "could not read: " + e.strerror
            header = "=== %s%s ===" % (name, (" (%s)" % note if note else ""))
            piece = header + ("\n" + body if body else "")
            if total + len(piece) > ATTACH_TOTAL_MAX:
                blocks.append("=== %s (omitted — attachment budget reached) ==="
                              % name)
                break
            total += len(piece)
            blocks.append(piece)
        if not blocks:
            return ""
        return ("The user attached these files as context for this message:\n\n"
                + "\n\n".join(blocks))

    @staticmethod
    def _safe_stage_name(name):
        """A dropped file's own name, reduced to a bare sandbox filename: the
        basename with path separators neutralised. `resolve()` in the executor
        already jails an escaping path, but keeping the staged name clean means a
        file called `../x` lands as `.._x` rather than erroring on the guard."""
        base = os.path.basename(str(name)) or "file"
        return base.replace("/", "_").replace("\\", "_") or "file"

    @staticmethod
    def _stage_path(safe_name):
        """Where a dropped file is staged, as `(op_path, shown_path)`.

        Attachments still land in SANDBOX_ROOT (the scratch dir), but the
        executor resolves a `put` against the WRITE root — which is now `/` —
        so the op path is the sandbox path expressed relative to that root.
        `shown_path` is what the model is told to read, absolute when writes
        are free."""
        target = os.path.join(SANDBOX_ROOT, ATTACH_STAGE_DIR, safe_name)
        root = os.path.realpath(WRITE_ROOT)
        real = os.path.realpath(target)
        if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
            rel = os.path.relpath(real, root)
        else:                       # a write root that excludes the sandbox
            rel = os.path.join(ATTACH_STAGE_DIR, safe_name)
        return (rel, real if WRITE_FREE else rel)

    def _stage_attachments(self, file_items):
        """Copy each dropped NON-image attachment into the sandbox on top (under
        ATTACH_STAGE_DIR) so the model's file tools can read the FULL file and
        edit it — not just the bounded inline text. Runs the same jailed
        executor the file tools use (`_fs_argv`, local on top / over the ssh
        master on book), once per file, SYNCHRONOUSLY: the files are small and
        must be in place before the model's first tool round. Best-effort — a
        failure (too big, unreadable, executor/ssh down) is NAMED, never silent
        (docs/DESIGN.md §10). Returns `(staged, errors)` where staged is a list
        of `{name, rel}` sandbox-relative paths."""
        staged, errors = [], []
        for it in file_items:
            path, name = it["path"], it["name"]
            try:
                size = os.path.getsize(path)
                if size > ATTACH_STAGE_MAX:
                    errors.append("%s (%d KB, over the %d KB stage limit)"
                                  % (name, size // 1024, ATTACH_STAGE_MAX // 1024))
                    continue
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError as e:
                errors.append("%s (could not read: %s)" % (name, e.strerror))
                continue
            rel, shown = self._stage_path(self._safe_stage_name(name))
            ok, err = self._run_fs_sync({
                "op": "put", "path": rel,
                "data": base64.b64encode(data).decode("ascii")})
            if ok:
                staged.append({"name": name, "rel": shown})
            else:
                errors.append("%s (%s)" % (name, err))
        return staged, errors

    @staticmethod
    def _stage_note(staged, errors):
        """The model-facing note that names where the staged attachments landed
        and how to use them, plus any that could not be staged (never silent)."""
        parts = []
        if staged:
            listing = ", ".join("`%s` (%s)" % (s["rel"], s["name"]) for s in staged)
            parts.append(
                "These attachments are also saved on the host at: "
                + listing + ". Use read_file to read one in full (the inlined "
                "text above may be truncated), and edit_file/write_file to "
                "modify it in place there.")
        if errors:
            parts.append("Could not stage for the file tools: "
                         + "; ".join(errors) + ".")
        return "\n\n".join(parts)

    def _run_fs_sync(self, req):
        """Run one sandbox-fs op and BLOCK for its result — used only for staging
        an attachment before the chat POST (the model tool loop stays async via
        `_run_fs_tool`). Returns `(ok, error_string)`. A copy over the already-
        open ssh master is subsecond; the timeouts are the honest failure path
        for a down executor, not a normal wait."""
        argv = self._fs_argv()
        proc = QProcess()
        proc.start(argv[0], argv[1:])
        if not proc.waitForStarted(4000):
            return False, "could not start the file executor"
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()
        if not proc.waitForFinished(8000):
            proc.kill()
            return False, "file executor timed out"
        result = self._fs_result(bytes(proc.readAllStandardOutput()),
                                 bytes(proc.readAllStandardError()),
                                 proc.exitCode())
        if "error" in result:
            return False, str(result["error"])
        return True, ""

    @staticmethod
    def _parse_history(history_json):
        """Validate the prior-turns array QML sends: only user/assistant roles
        with non-empty string content survive (QML already drops error rows and
        empty streams before building it; this is the defensive re-check on the
        Python side of a QML->Python string boundary)."""
        try:
            arr = json.loads(history_json or "[]")
        except ValueError:
            return []
        if not isinstance(arr, list):
            return []
        out = []
        for t in arr:
            if not isinstance(t, dict):
                continue
            role, content = t.get("role"), t.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                out.append({"role": role, "content": content})
        return out

    # ---- working memory: the tool rounds of the turns before this one -------

    @staticmethod
    def _user_texts(msgs):
        """The user messages of a message list, in order — the fingerprint a
        carried list is matched on.

        USER messages specifically, because they are the one part both sides
        agree on: the chat log splits a long answer into several assistant rows
        (one per tool round) while the message list holds one, so comparing
        assistant text would fail on exactly the turns worth carrying."""
        return [str(m.get("content") or "") for m in msgs
                if m.get("role") == "user"]

    def _carry(self, hist):
        """The previous turn's full message list when this turn continues the
        same conversation, else None.

        `hist` is what QML sent (user/assistant text only). If its user turns
        are the ones the carried list already has, this is the next turn of that
        same chat and the carried list is strictly richer — it has the tool
        calls and results in it. Anything else (a switched session, a reopened
        one, an edited log, a fresh app) fails the match and the turn is built
        from `hist` exactly as it always was.
        """
        if not self._prior:
            return None
        # `_prior_users` is the RAW prompts, not the user messages actually
        # sent: a turn that carried dropped files (or a `continue`) puts extra
        # text — and extra user messages — into the list, and comparing those
        # would switch the memory off on exactly the turns that used it most.
        if self._prior_users != self._user_texts(hist):
            return None
        return self._trim_carry([dict(m) for m in self._prior])

    @staticmethod
    def _trim_carry(msgs):
        """Charge `TOOL_CARRY_CHARS` newest-first; stub what does not fit.

        The assistant messages that CALLED the tools are never touched — a model
        that can see it already ran `read_file` on a path does not run it again,
        which is the whole point. Only the output is dropped, and it says so.
        """
        spent = 0
        for m in reversed(msgs):
            if m.get("role") != "tool":
                continue
            body = str(m.get("content") or "")
            if spent + len(body) <= TOOL_CARRY_CHARS:
                spent += len(body)
            else:
                m["content"] = TOOL_CARRY_STUB
        return msgs

    def _remember_turn(self):
        """Snapshot the turn that just finished, tool rounds and all.

        The final assistant answer is appended here rather than in the loop:
        `_on_finished` only appends an assistant message when it is going round
        again, so the last one would otherwise be missing from the memory of the
        turn. The system message is dropped — it is rebuilt every turn (the
        clock in it moves) and carrying a stale one would pin the model to an
        old `now`.
        """
        msgs = [m for i, m in enumerate(self._messages)
                if m.get("role") != "system" and i not in self._synthetic]
        answer = (self._partial_prefix + self._acc_content).strip()
        if answer:
            msgs.append({"role": "assistant", "content": answer})
        self._prior = msgs
        self._prior_users = list(self._pending_users)

    @staticmethod
    def _research_budget(prompt):
        """How wide the web search should fan out for this prompt.

        A cheap keyword+length heuristic, not a model call: a simple, focused
        ask (a weather lookup, a definition, a single fact) scores low and gets
        a small source cap with a "do not fan out" instruction; a broad research
        question (compare, overview, history of, several sub-questions) scores
        high and may pull many sources. Returns the per-search `max_results`
        cap and the sentence handed to the model so the guidance and the cap
        agree. The point is proportion — the ability to go wide is kept, not
        removed (a "10 hour weather report" was pulling 20 sources)."""
        text = " " + (prompt or "").lower() + " "
        words = re.findall(r"[a-z0-9']+", text)
        n = len(words)
        score = 0
        BROAD = ("compare", "comprehensive", "in depth", "in-depth", "deep dive",
                 "research", "analyz", "analyse", "overview", "survey",
                 "pros and cons", "advantages", "disadvantages", "history of",
                 "everything about", "trade-off", "tradeoff", " versus ", " vs ",
                 "review of", "state of the", "landscape", "alternatives",
                 "options for", "explain how", "why does", "why do", "how does")
        for m in BROAD:
            if m in text:
                score += 2
        q = text.count("?")
        if q > 1:                       # several distinct questions widen it
            score += q - 1
        if n >= 40:
            score += 2
        elif n >= 20:
            score += 1
        NARROW = ("weather", "temperature", "forecast", "what time", "current time",
                  "define ", "definition of", "how do you spell", "capital of",
                  "who is ", "who was ", "when is ", "when was ", "where is ",
                  "how tall", "how far", "how old", "how much is", "convert ",
                  "how many", "what is the ", "what's the ")
        for m in NARROW:
            if m in text:
                score -= 2
        if n <= 8:                      # a terse prompt is usually a simple ask
            score -= 1
        if score <= -1:
            cap, depth = RESEARCH_MIN, ("This is a simple, focused question. If "
                "you need the web at all, one search returning a few sources is "
                "plenty — do not fan out into many searches.")
        elif score <= 2:
            cap, depth = 5, ("Search the web only as much as this actually needs "
                "— a couple of focused searches at most, not a broad sweep.")
        else:
            cap, depth = RESEARCH_MAX, ("This is a broad question; you may run "
                "several searches to cover it well, but keep each one on point.")
        return {"max_results": cap, "guidance": depth}

    def _memory_block(self):
        """The durable memories oracle has saved, rendered for the system prompt.

        Prepended to every turn so the model recalls its own memories as real
        facts without having to call list_memories first (distinct from the
        session tools, which read past TRANSCRIPTS). Capped to keep the context
        bounded: newest-updated first, at most MEMORY_CTX_MAX entries and
        MEMORY_CTX_CHARS characters. Empty when it has saved nothing yet."""
        mems = self._memories or []
        if not mems:
            return ""
        lines, used = [], 0
        for m in mems[:MEMORY_CTX_MAX]:
            text = str(m.get("text", "")).strip()
            if not text:
                continue
            line = "- [%s] %s" % (m.get("id", ""), text)
            if used + len(line) > MEMORY_CTX_CHARS:
                break
            lines.append(line)
            used += len(line)
        if not lines:
            return ""
        return ("Durable memories you have saved (real facts you chose to "
                "remember — trust them as true, and keep them current with "
                "save_memory/delete_memory as you learn more):\n" + "\n".join(lines))

    def _system_prompt(self, research=""):
        """A minimal system message that pins an unambiguous `now`. The model
        otherwise dates itself from its training; here it gets the real instant
        in local time and UTC, and is told to call get_current_time for any
        other zone rather than guessing a DST offset.

        Local time leads: a bare "what time is it" means "here", and UTC can be
        a calendar day ahead of a negative-offset zone (Alaska at night, say) —
        leading with UTC's date made the model report that later date as "the
        current time" and it read as reporting the future. Naming local time
        first as *the* current time, with UTC only as a cross-reference, is
        what keeps the model's default answer matching what "now" means to him."""
        now = datetime.now(timezone.utc)
        local = now.astimezone()
        base = ("The current time right now is %s local time (%s), which is "
                "%s UTC. When asked for the current time or date with no place "
                "specified, answer with the local time above, not the UTC one. "
                "For the time or date somewhere else, call get_current_time "
                "with an IANA timezone rather than converting it yourself."
                % (local.strftime("%Y-%m-%d %H:%M:%S"),
                   local.tzname() or local.strftime("%z"),
                   now.strftime("%Y-%m-%d %H:%M:%S")))
        memory_block = self._memory_block()
        if memory_block:
            base += "\n\n" + memory_block
        base += "\n\n" + RECALL_GUIDANCE
        base += "\n\n" + SAVE_GUIDANCE
        base += "\n\n" + CAPABILITY_NOTE
        base += "\n\n" + PERSISTENCE_NOTE
        base += "\n\n" + MARKER_NOTE
        tools = tools_note()
        if tools:
            base += "\n\n" + tools
        skills = skills_note()
        if skills:
            base += "\n\n" + skills
        agents = agents_note()
        if agents:
            base += "\n\n" + agents
        base += "\n\n" + authoring_note()
        if research:
            base += "\n\n" + research
        # His chosen base (a preset or his own custom text) LEADS — the time
        # line, memory block and recall/save guidance above always run whatever
        # base is active; only this leading block swaps.
        lead = self._base_prompt()
        if lead:
            base = lead + "\n\n" + base
        return base

    def _run_job_tool(self, name, args, idx, remaining, calls):
        """run_job / job_status / job_log / job_stop, through the one `Jobs`
        object the window draws from — so what the model is told and what he
        sees in the tray are the same read of the same directory, never two
        (docs/DESIGN.md §10)."""
        a = args if isinstance(args, dict) else {}
        jobs = self._jobs
        if jobs is None:
            result = {"error": "background jobs are not available"}
        elif name == "run_job":
            command = str(a.get("command") or a.get("code") or "").strip()
            if not command:
                result = {"error": "run_job needs a command"}
            else:
                result = jobs.start(command,
                                    lang=str(a.get("lang") or "bash"),
                                    cwd=str(a.get("cwd") or ""),
                                    label=str(a.get("label") or "job"))
                result.setdefault("note", "it is running in the background; "
                                  "come back to it with job_status")
        elif name == "job_status":
            result = jobs.status(str(a.get("id") or ""))
        elif name == "job_log":
            try:
                lines = int(a.get("lines") or 80)
            except (TypeError, ValueError):
                lines = 80
            result = jobs.status(str(a.get("id") or ""), tail=max(1, lines))
        else:
            result = jobs.stop(str(a.get("id") or ""))
        remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                  "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    def _run_get_tools(self, args, idx, remaining, calls):
        """Attach tools by name or group, and hand their schemas back.

        Synchronous: it reads two dicts. The result carries the FULL schema of
        everything it attached, so the model can call correctly in the very
        next round rather than guessing argument names — that is the half of
        this that makes one extra step enough."""
        raw = str(args.get("names", "") or args.get("name", "") or "")
        parts = [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]
        reg = self._main_registry()
        wanted, unknown = [], []
        for p in parts:
            low = p.lower()
            if low in EXTRA_TOOL_GROUPS:
                wanted += EXTRA_TOOL_GROUPS[low]
            elif low in AGENT_TOOL_GROUPS:
                wanted += AGENT_TOOL_GROUPS[low]
            elif low == "all":
                wanted += list(reg)
            elif p in reg:
                wanted.append(p)
            else:
                unknown.append(p)
        attached, schemas = [], []
        for n in wanted:
            if n in reg and n not in attached:
                attached.append(n)
                schemas.append(reg[n])
        self._extra_tools.update(attached)
        result = {"attached": attached, "schemas": schemas}
        if unknown:
            result["not_found"] = unknown
            result["available"] = sorted(n for n in reg
                                         if n not in CORE_TOOL_NAMES)
        if not attached and not unknown:
            result["error"] = ("get_tools needs names — see the 'Other tools' "
                               "list in your instructions.")
        remaining["sink"][idx] = {"role": "tool", "tool_name": "get_tools",
                                  "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    def _time_now(self, tz_name, idx, remaining, calls):
        """Resolve the current time in an IANA zone through zoneinfo (real DST
        rules), fed back like any other tool result. Synchronous — a wall clock
        needs no subprocess and the instant is the same on either host."""
        now = datetime.now(timezone.utc)
        tz_name = (tz_name or "").strip()
        try:
            zone = ZoneInfo(tz_name) if tz_name else timezone.utc
            here = now.astimezone(zone)
            result = {"timezone": tz_name or "UTC",
                      "iso": here.isoformat(),
                      "date": here.strftime("%Y-%m-%d"),
                      "time": here.strftime("%H:%M:%S"),
                      "abbreviation": here.tzname() or "",
                      "utc_offset": here.strftime("%z"),
                      "utc": now.isoformat()}
        except (ZoneInfoNotFoundError, ValueError):
            result = {"error": "unknown timezone: " + tz_name}
        remaining["sink"][idx] = {"role": "tool", "tool_name": "get_current_time",
                                   "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    def _describe_self(self, idx, remaining, calls):
        """Report EVERYTHING the model can access about itself this turn — model
        and provider, the machine, its context window and fill, generation
        speed, active persona, saved memories, available tools, sampling options
        and the conversation's size. Synchronous — every fact is in-process or
        read live off this host, so it needs no subprocess and is host-neutral.
        The machine facts are re-derived at call time (platform / os / proc)
        rather than hardcoded, so nothing from the private hardware notes is
        baked into this public source."""
        # The persona / active base prompt (label + the actual text it leads with).
        choice = self._prompt_choice
        persona = ("custom" if choice == "custom"
                   else next((p["label"] for p in PROMPT_PRESETS
                              if p["id"] == choice), choice))
        base_text = self._base_prompt()
        # The durable memories, capped so a big store cannot blow the reply.
        mems = [str(m.get("text", "")).strip()
                for m in (self._memories or []) if str(m.get("text", "")).strip()]
        # This conversation's size, counted off the message list built for the turn.
        user_turns = sum(1 for m in self._messages if m.get("role") == "user")
        asst_turns = sum(1 for m in self._messages if m.get("role") == "assistant")
        result = {
            "model": self._model or "(none selected)",
            "provider": {"backend": "ollama", "endpoint": OLLAMA},
            "app": "chatter (the oracle ollama chat window)",
            "host": socket.gethostname(),
            "os": self._os_pretty(),
            "arch": platform.machine(),
            "cpu_logical": os.cpu_count(),
            "memory_total": self._mem_total(),
            "python": platform.python_version(),
            "context": {
                "window_tokens": self._ctx_max or "unknown",
                "model_trained_ceiling": self._ctx_train or "unknown",
                "used_tokens": self._ctx_used,
                "num_ctx_requested": self._num_ctx,
            },
            "last_tokens_per_sec": round(self._tps, 1) if self._tps else 0,
            "native_capabilities": self._caps,
            "file_access": {"read_root": READ_ROOT, "write_root": WRITE_ROOT,
                            "writes_jailed": not WRITE_FREE,
                            "scratch_dir": SANDBOX_ROOT,
                            "code_runner_network": EXEC_NET},
            "persona": persona,
            "base_prompt": (base_text[:800] if base_text
                            else "(default — no persona)"),
            "saved_memories": {"count": len(mems), "items": mems[:40]},
            "conversation": {"your_prompts": user_turns,
                             "your_replies_so_far": asst_turns},
            "tools_available": self._offered_tool_names(),
            "tools_attached_now": sorted(
                t["function"]["name"] for t in self._offered_tools()),
            "sampling": {"num_ctx": self._num_ctx,
                         "temperature": "model default (chatter does not override)"},
        }
        remaining["sink"][idx] = {"role": "tool", "tool_name": "describe_self",
                                   "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    @staticmethod
    def _builtin_tools():
        """Every tool the APP itself defines. Split out from `_all_tools` so a
        custom tool of his can never shadow one of these: the collision is
        decided against this list, not against a hand-kept copy of it."""
        return (list(FILE_TOOLS) + [WEB_SEARCH_TOOL, TIME_TOOL, SELF_TOOL,
                IMAGE_TOOL, SEARCH_IMAGE_TOOL, VIEW_IMAGE_TOOL, SHOW_IMAGE_TOOL,
                SCREENSHOT_TOOL, MAKE_IMAGE_TOOL, MAKE_VIDEO_TOOL, BOORU_TOOL,
                VIDEO_TOOL, PLAYER_TOOL,
                MUSIC_TOOL, LASTFM_TOOL, MODEL_TOOL,
                FETCH_URL_TOOL,
                CALL_API_TOOL, EXEC_TOOL, BASH_TOOL]
                + list(SESSION_TOOLS) + list(MEMORY_TOOLS) + list(AUTHOR_TOOLS)
                + [GET_TOOLS_TOOL] + list(JOB_TOOLS)
                + [t for t in [skill_tool(), spawn_agent_tool()] if t])

    @staticmethod
    def _all_tools():
        """EVERY tool offered to the main agent this turn, built once.

        `_post_chat` sends this and `describe_self` reports it, so the payload
        and the list the model is told about cannot drift — they were written
        out separately until 2026-08-23 and had already started to. The two
        catalog-built tools (skills, subagents) are absent when nothing is
        installed, so neither is ever offered as an affordance that is not
        there (docs/DESIGN.md §10)."""
        return Ollama._builtin_tools() + custom_tool_defs()

    @staticmethod
    def _main_registry():
        """`{name: schema}` for every tool the MAIN agent can reach, attached or
        not. `tools_note` indexes it and `get_tools` attaches out of it."""
        reg = {}
        for t in Ollama._all_tools():
            if isinstance(t, dict) and isinstance(t.get("function"), dict):
                name = t["function"].get("name")
                if name:
                    reg[str(name)] = t
        return reg

    def _offered_tools(self):
        """What goes in THIS request's `tools`: the core set, plus whatever
        `get_tools` has attached this turn. Everything else is in the index in
        the system prompt (`tools_note`) — and reachable regardless, since
        `_dispatch_tool` goes by name."""
        reg = self._main_registry()
        want = list(CORE_TOOL_NAMES) + [n for n in self._extra_tools
                                        if n not in CORE_TOOL_NAMES]
        return [reg[n] for n in want if n in reg]

    @staticmethod
    def _offered_tool_names():
        """Every tool the main agent can REACH — the whole registry, not just
        what is attached to the current message. `_dispatch_tool` resolves by
        name, so this is the true answer to "what can you call" (docs/DESIGN.md
        §10 — a true list, not a remembered one); `tools_attached_now` beside it
        in `describe_self` is the smaller list carried on the wire."""
        names = [t.get("function", {}).get("name", "") for t in Ollama._all_tools()
                 if isinstance(t, dict) and t.get("function")]
        return sorted(n for n in names if n)

    @staticmethod
    def _os_pretty():
        """A human OS name (e.g. 'Fedora Linux Asahi Remix 42'), from
        /etc/os-release when readable, else uname's system + release."""
        try:
            rel = platform.freedesktop_os_release()
            name = rel.get("PRETTY_NAME") or rel.get("NAME")
            if name:
                return name
        except (OSError, AttributeError):
            pass
        return (platform.system() + " " + platform.release()).strip()

    @staticmethod
    def _mem_total():
        """Total RAM as a human string, read live from /proc/meminfo; '' if it
        cannot be read (never guessed)."""
        try:
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return "%.1f GiB" % (kb / (1024 * 1024))
        except (OSError, ValueError, IndexError):
            pass
        return ""

    def _ctx_room(self):
        """Is there still context room for another tool round?

        Four characters to the token is the standard rough count and is all this
        needs to be: it decides between one more tool round and wrapping up, and
        both are safe. It counts the whole message list — system prompt, history,
        every tool result so far — because that is what the next POST carries.
        """
        chars = sum(len(str(m.get("content") or "")) for m in self._messages)
        return (chars / 4) < (self._num_ctx * TOOL_CTX_FRACTION)

    def _post_chat(self):
        """POST the current message list, streaming, offering every tool.
        Re-entered after each tool round."""
        payload = {
            "model": self._model,
            "messages": self._messages,
            "stream": True,
            "options": dict(sampler_for(self._model),
                            num_ctx=self._num_ctx),
        }
        # The WRAP-UP round carries no tools at all: `_on_finished` sets
        # `_no_tools` when the model is still calling tools at MAX_TOOL_ROUNDS,
        # and a request with no `tools` key leaves it nothing to do but write
        # the answer. Offering them again is what produced an EMPTY reply.
        if self._no_tools:
            body = json.dumps(payload).encode("utf-8")
            return self._send_chat(body)
        # ALL tools are offered on EVERY turn (his call — no per-tool toggle):
        # the file tools and web_search alike. A model with no tool support will
        # reject a request carrying tools — the tradeoff of always-on tools,
        # spelled out in apps/oracle/AGENTS.md; point oracle at a tool-capable
        # model.
        payload["tools"] = self._offered_tools()
        body = json.dumps(payload).encode("utf-8")
        self._send_chat(body)

    def _send_chat(self, body):
        """POST one already-built /api/chat body and wire the stream up."""
        req = QNetworkRequest(QUrl(OLLAMA + "/api/chat"))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        self._buf = b""
        self._acc_content = ""
        self._tool_calls = []
        self._done_reason = ""
        reply = self._nam.post(req, body)
        self._reply = reply
        reply.readyRead.connect(lambda: self._on_stream(reply))
        reply.finished.connect(lambda: self._on_finished(reply))

    @Slot()
    def cancel(self):
        # Drops the whole turn: a pending tool fetch checks `busy` and bails, so
        # a search still in flight never re-posts to a cancelled turn.
        self._set_busy(False)
        self._stop_generating()
        if self._reply is not None:
            r, self._reply = self._reply, None
            r.readyRead.disconnect()
            r.finished.disconnect()
            r.abort()
            r.deleteLater()

    def _stop_generating(self):
        """Kill any render this turn started, backend and all [his, 2026-08-24].

        The generator handles SIGTERM by interrupting ComfyUI and deleting what
        it queued (apps/painter/tools/smoke.py), which is the half that matters:
        killing the script alone leaves the GPU sampling a clip nobody is
        waiting for. The command is `exec`d by its shell so the signal lands on
        python and not on a bash that is only waiting for it. On book the
        generator is at the far end of an ssh, and terminating the local ssh
        does NOT signal it — the render there runs to its own end.
        """
        procs, self._gen_procs = list(self._gen_procs), []
        for proc in procs:
            try:
                if proc.state() == QProcess.ProcessState.NotRunning:
                    continue
                proc.terminate()
                # It has the interrupt to POST before it goes; SIGKILL only if
                # it is still there after that.
                QTimer.singleShot(6000, lambda p=proc: (
                    p.kill() if p.state() != QProcess.ProcessState.NotRunning
                    else None))
            except RuntimeError:
                continue
        if procs:
            self.genFinished.emit(False)

    def _on_stream(self, reply):
        if reply is not self._reply:
            return
        self._buf += bytes(reply.readAll().data())
        # NDJSON: one JSON object per line, and a read may split a line.
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("error"):
                self.replyError.emit(str(obj["error"]))
                continue
            msg = obj.get("message") or {}
            # A "thinking" model streams its reasoning in `thinking` with an
            # empty `content` until it starts answering; surface it (drawn
            # dimmed) so the window is not blank while it reasons.
            think = msg.get("thinking", "")
            if think:
                self.replyThinking.emit(think)
                # ollama streams one token per NDJSON frame, so a running frame
                # count is the reasoning's live token count — surfaced so the
                # collapsed heading can show progress while it thinks.
                self._think_tokens += 1
                self.replyThinkTokens.emit(self._think_tokens)
            piece = msg.get("content", "")
            if piece:
                self._acc_content += piece
                # A running tok/s estimate: clock from the first content frame,
                # one frame ≈ one token (same assumption the reasoning counter
                # uses). Settled to ollama's exact numbers on the done frame below.
                if self._resp_t0 == 0.0:
                    self._resp_t0 = time.monotonic()
                self._resp_tokens += 1
                dt = time.monotonic() - self._resp_t0
                if dt > 0.2 and self._resp_tokens > 1:
                    self._set_tps(self._resp_tokens / dt)
                self.replyChunk.emit(piece)
            # Tool calls arrive assembled by ollama (not partial deltas); a turn
            # may carry several. Accumulate them for the round.
            calls = msg.get("tool_calls")
            if calls:
                self._tool_calls.extend(calls)
            # The final frame carries ollama's own token accounting — the exact
            # generation rate, which replaces the running estimate.
            if obj.get("done"):
                self._done_reason = str(obj.get("done_reason") or "")
                ec = obj.get("eval_count")
                ed = obj.get("eval_duration")     # nanoseconds
                if isinstance(ec, (int, float)) and isinstance(ed, (int, float)) \
                        and ec > 0 and ed > 0:
                    self._set_tps(ec / (ed / 1e9))
                # How full the context is now: what ollama actually read as the
                # prompt plus what it just generated — the real fill, not an
                # estimate (docs/DESIGN.md §10).
                pec = obj.get("prompt_eval_count")
                used = 0
                if isinstance(pec, (int, float)) and pec > 0:
                    used += int(pec)
                if isinstance(ec, (int, float)) and ec > 0:
                    used += int(ec)
                if used > 0:
                    self._set_ctx_used(used)
                    # THE WINDOW FILLED IN THIS ROUND. ollama shifts the
                    # context rather than failing, so the round after it reads
                    # a prompt it no longer entirely has — and the answer that
                    # comes out can simply stop mid-sentence with a perfectly
                    # ordinary `done_reason` of "stop". Remember that the turn
                    # was squeezed; `_truncation_reason` is what does something
                    # about it.
                    if used >= self._num_ctx * CTX_FULL_FRACTION:
                        self._squeezed = True

    #: Characters an answer can legitimately END on: sentence punctuation, a
    #: closed markdown span, a table row, a link, a symbol or an emoji. A reply
    #: whose last line ends on anything else stopped in the middle of a word or
    #: a clause.
    _CLOSERS = ".!?…:;)]}>\"'`*_~|"

    @classmethod
    def _ends_abruptly(cls, text):
        """Does this answer stop mid-sentence?

        SHAPE ALONE IS NOT ENOUGH TO ACT ON — measured across his saved
        sessions, one finished reply in nine ends on a bare word (a bullet
        list, a heading, a trailing link), so treating that as truncation would
        put a `continue` on answers that are complete. It is only ever read
        beside `_squeezed`, in `_truncation_reason`.
        """
        s = (text or "").rstrip()
        if not s:
            return False
        if s.count("```") % 2:          # a code fence that never closed
            return True
        last = [ln for ln in s.split("\n") if ln.strip()][-1].rstrip()
        end = last[-1]
        if end in cls._CLOSERS:
            return False
        # An emoji or any other standalone symbol is a deliberate ending.
        return unicodedata.category(end) not in ("So", "Sk", "Sm", "Sc")

    def _truncation_reason(self):
        """Why this answer stopped short, or "" if it did not.

        Two ways a reply ends in the middle of a sentence, and only one of them
        announces itself:

        * `"length"` — ollama's own `done_reason`, the model's token ceiling.
        * `"context"` — the TURN ran out of window (a round filled
          `CHAT_NUM_CTX`, or the tool loop was cut short into its wrap-up
          round) and the answer it then wrote stops mid-sentence. ollama calls
          that an ordinary `"stop"`: it shifted the context, generated, and
          finished normally as far as the server is concerned. Observed
          2026-08-23 — a music-library turn spent its window on tool rounds and
          handed him a table that breaks off mid-row with no way on, because
          nothing in the app knew the turn had been squeezed.
        """
        if self._done_reason == "length":
            return "length"
        if self._squeezed and self._ends_abruptly(self._acc_content):
            return "context"
        return ""

    def _on_finished(self, reply):
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        err = reply.error()
        err_str = reply.errorString()
        reply.deleteLater()
        if err == QNetworkReply.NetworkError.OperationCanceledError:
            return                      # cancel() already cleared busy
        if err != QNetworkReply.NetworkError.NoError:
            self._set_busy(False)
            self.replyError.emit(err_str)
            return
        # A tool round: run the calls, feed the results back, and let the model
        # continue. Past the cap, stop looping and take the answer as-is.
        if (self._tool_calls and self._rounds < MAX_TOOL_ROUNDS
                and self._ctx_room()):
            self._rounds += 1
            self._messages.append({"role": "assistant",
                                   "content": self._acc_content,
                                   "tool_calls": self._tool_calls})
            self._run_tool_calls(self._tool_calls)
            return
        # OUT of rounds or out of context, and STILL calling tools. Stopping here is what handed him
        # an EMPTY message (observed 2026-08-22: four run_bash rounds hunting
        # for a directory, then nothing at all, twice in a row) — the model's
        # last frame was tool calls and no prose, so there was no answer to
        # take "as-is". So run this round's calls too and re-post ONCE with no
        # tools and TOOL_CAP_PROMPT, which leaves it nothing to do but answer.
        if self._tool_calls and not self._no_tools:
            self._no_tools = True
            self._squeezed = True    # it is answering because it ran out, not
                                     # because it was finished looking

            self._messages.append({"role": "assistant",
                                   "content": self._acc_content,
                                   "tool_calls": self._tool_calls})
            self._run_tool_calls(self._tool_calls)
            return
        # A model that TYPED an image instead of calling fetch_image: attach it
        # anyway, rather than leaving him a reply full of pictures that are not
        # there. replyDone waits for those downloads.
        if self._attach_typed_images():
            return
        if self._attach_typed_videos():
            return              # `_typed_video_done` ends the turn instead
        self._remember_turn()
        self._set_busy(False)
        reason = self._truncation_reason()
        if reason:
            self.replyTruncated.emit(reason)
        self.replyDone.emit()

    #: How many `![](…)` images one reply may pull in on its own. A model
    #: listing a booru page can type a dozen; four is what fits a turn.
    MD_IMAGE_MAX = 4

    #: …and how many VIDEOS. Two: a reply that recommends listening is naming
    #: one or two things, not a playlist.
    MD_VIDEO_MAX = 2

    #: A model that TYPED a call instead of making one. Observed 2026-08-23 in
    #: his own session: the reply carried `{{show_video|https://…}}` as literal
    #: text and no card was drawn — *"it seems something happaned to where the
    #: video was not shown inline like how it should"*. Every brace-marker shape
    #: a model reaches for when it decides to invent a syntax.
    VIDEO_MARKER_RE = re.compile(
        r"\{\{\s*(?:show_video|video|play_video)\s*[|:(=]\s*"
        r"(https?://[^\s}|)]+)\s*\)?\s*\}\}", re.I)

    #: A video URL written as prose or as a markdown link. Attached too — "show
    #: me a youtube video" is answered with a card, not with a link he has to
    #: click out of the window (docs/DESIGN.md §10).
    VIDEO_URL_RE = re.compile(
        r"https?://(?:www\.)?(?:youtube\.com/watch\?[^\s)\]<]*v=[\w-]+"
        r"|youtu\.be/[\w-]+|vimeo\.com/\d+)[^\s)\]<>{}\"']*", re.I)

    def _attach_typed_videos(self):
        """Draw the videos the reply NAMED but never called for. True if any.

        The same gap `_attach_typed_images` closes at the other end, and the
        same fix: the tool exists, the model wrote the URL into its prose
        instead of calling it, and the window drew nothing. Since 2026-08-23
        `show_video` is not even on the wire every turn (it is in the tool
        index), so typing it is the MORE likely failure, not less.

        A `{{show_video|…}}` marker is replaced in the prose by the bare URL —
        the card carries the video, and if the card fails he can still see what
        it was. A URL the model merely mentioned is left exactly as written.
        """
        text = self._acc_content or ""
        found, cleaned = [], text
        for m in self.VIDEO_MARKER_RE.finditer(text):
            found.append(m.group(1))
            cleaned = cleaned.replace(m.group(0), m.group(1))
        # The CLEANED text, not the original: a marker's own URL would
        # otherwise be found a second time with the closing braces stuck to it.
        for m in self.VIDEO_URL_RE.finditer(cleaned):
            url = m.group(0).rstrip(".,;:")
            if url not in found:
                found.append(url)
        found = [u for u in found if u not in self._videos_shown]
        found = found[:self.MD_VIDEO_MAX]
        if cleaned != text:
            self._acc_content = cleaned
            self.replyBodyFixed.emit(cleaned)
        if not found:
            return False
        self._videos_shown.update(found)
        self._md_videos = {"n": len(found)}
        for url in found:
            self._show_video(url, "", None, None, None)
        return True

    def _typed_video_done(self):
        """One typed video resolved (or failed). The turn ends when the last
        one is in, so the session that gets saved has the card in it."""
        if not self._md_videos.get("n"):
            return
        self._md_videos["n"] -= 1
        if self._md_videos["n"] > 0 or not self._busy:
            return
        self._remember_turn()
        self._set_busy(False)
        reason = self._truncation_reason()
        if reason:
            self.replyTruncated.emit(reason)
        self.replyDone.emit()

    def _attach_typed_images(self):
        """Fetch the markdown images in the finished reply. True if any started.

        Models — gemma4 reliably — answer "show me pictures of X" by WRITING
        `![alt](url)` into the reply instead of calling `fetch_image`, however
        plainly the tool says not to (observed 2026-08-22: four typed images,
        nothing attached, and his "you didnt attach them to your message
        though"). `MarkdownText` demotes image markdown to a link on purpose —
        Qt would fetch it on render, at its own pixel size — so the picture
        simply never appeared.

        This closes the gap at the other end: the same download `fetch_image`
        does, capped and content-checked, feeding the same `images` row QML
        already draws. The demoted link stays in the prose, so nothing is
        hidden either way (docs/DESIGN.md §10).
        """
        found = []
        for m in re.finditer(r"!\[([^\]]*)\]\(\s*(https?://[^\s)]+)", self._acc_content):
            url = m.group(2).rstrip(")")
            alt = m.group(1).strip()
            if url in self._images_shown:
                # ALREADY FETCHED THIS TURN — so DRAW IT HERE TOO, rather than
                # skipping it [his, 2026-08-22]. A turn that gathers pictures
                # over several rounds and then writes them up ends with a list
                # naming eleven of them and a bubble holding none: the pictures
                # are up-thread, on the round bubbles that fetched them, and the
                # summary's own markdown is demoted to links (MarkdownText.qml).
                # The file is already on disk, so this is a redraw, not a second
                # download — and `_row_urls` keeps one bubble from showing the
                # same picture twice.
                entry = self._image_entries.get(url)
                if entry and url not in self._row_urls:
                    self._emit_image(dict(entry, alt=alt or entry.get("alt", "")))
                continue
            self._images_shown.add(url)
            found.append((url, alt))
            if len(found) >= self.MD_IMAGE_MAX:
                break
        if not found:
            return False
        self._md_images = {"n": len(found)}
        for url, alt in found:
            self._fetch_image(url, alt, None, self._md_images, None)
        return True

    def _typed_image_done(self, remaining):
        """The last typed-markdown image landed: now the turn is over."""
        remaining["n"] -= 1
        if remaining["n"] > 0 or not self._busy:
            return
        self._remember_turn()
        self._set_busy(False)
        reason = self._truncation_reason()
        if reason:
            self.replyTruncated.emit(reason)
        self.replyDone.emit()

    # ---- the web_search tool loop ----

    @staticmethod
    def _new_round(calls, done=None):
        """One tool round, as an OBJECT rather than instance state.

        `sink` is where this round's results land, `n` counts the calls still
        outstanding, and `done` — when set — is what runs instead of the chat
        loop once they are all in. Every tool method already took `remaining`;
        making it carry the sink is what lets a SUBAGENT reuse the same tool
        implementations concurrently with the turn that spawned it, instead of
        the two rounds overwriting one shared list."""
        n = len(calls)
        r = {"n": n, "sink": [None] * n}
        if done is not None:
            r["done"] = done
        return r

    @staticmethod
    def _call_parts(call):
        """`(name, args)` from one ollama tool call; a string `arguments` (some
        models send JSON text) is decoded, and anything unparseable is {}."""
        fn = call.get("function") or {}
        name = fn.get("name", "")
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        return name, args

    def _run_tool_calls(self, calls):
        """Dispatch each tool call; when the last result is in, re-post the
        chat with the tool messages appended. Calls run concurrently."""
        remaining = self._new_round(calls)
        reg = self._main_registry()
        for i, call in enumerate(calls):
            name, args = self._call_parts(call)
            # IT CALLED SOMETHING OFF THE INDEX. `_dispatch_tool` runs it by
            # name whether or not the schema was on the wire, so the only thing
            # missing is for the rest of the turn to keep it — no round wasted
            # on a `get_tools` for a tool it has already used correctly.
            if name in reg and name not in CORE_TOOL_NAMES:
                self._extra_tools.add(name)
            # Name every call in the transcript, whatever it is — the generic
            # indicator, so a tool with no richer disclosure is never silent.
            self.toolCallStarted.emit(name or "tool")
            self._dispatch_tool(name, args, i, remaining, calls)

    def _dispatch_tool(self, name, args, i, remaining, calls):
        """Run ONE tool call into `remaining`'s sink at index `i`.

        Split out of `_run_tool_calls` so the subagent loop (`_spawn_agent`)
        reaches every tool through the same branch rather than a second copy of
        it that could drift — the caller decides which names it offers, this
        decides what each one does."""
        if name == "web_search":
            self._tavily_search(str(args.get("query", "")).strip(),
                                i, remaining, calls)
        elif name == "get_current_time":
            self._time_now(str(args.get("timezone", "")), i, remaining, calls)
        elif name == "describe_self":
            self._describe_self(i, remaining, calls)
        elif name in IMAGE_TOOL_NAMES:
            self._fetch_image(str(args.get("url", "")).strip(),
                              str(args.get("alt", "")).strip(),
                              i, remaining, calls)
        elif name in SHOW_IMAGE_TOOL_NAMES:
            self._show_image(args, i, remaining, calls)
        elif name in MAKE_IMAGE_TOOL_NAMES:
            self._make_image(args, i, remaining, calls)
        elif name in MAKE_VIDEO_TOOL_NAMES:
            self._make_video(args, i, remaining, calls)
        elif name in BOORU_TOOL_NAMES:
            self._booru_tags(args, i, remaining, calls)
        elif name in SCREENSHOT_TOOL_NAMES:
            self._screenshot(args, i, remaining, calls)
        elif name in VIEW_IMAGE_TOOL_NAMES:
            self._view_image(args, i, remaining, calls)
        elif name in MODEL_TOOL_NAMES:
            self._run_model_tool(args, i, remaining, calls)
        elif name in MUSIC_TOOL_NAMES:
            self._run_music_tool(args, i, remaining, calls)
        elif name in LASTFM_TOOL_NAMES:
            self._run_lastfm_tool(args, i, remaining, calls)
        elif name in PLAYER_TOOL_NAMES:
            self._run_player_tool(args, i, remaining, calls)
        elif name in VIDEO_TOOL_NAMES:
            self._show_video(str(args.get("url", "")).strip(),
                             str(args.get("alt", "")).strip(),
                             i, remaining, calls)
        elif name in SEARCH_IMAGE_TOOL_NAMES:
            self._search_images(str(args.get("query", "")).strip(),
                                i, remaining, calls)
        elif name in FETCH_URL_TOOL_NAMES:
            self._fetch_url(str(args.get("url", "")).strip(),
                            args.get("offset", 0), i, remaining, calls)
        elif name in CALL_API_TOOL_NAMES:
            self._call_api(args, i, remaining, calls)
        elif name in FILE_TOOL_NAMES:
            self._run_fs_tool(name, args, i, remaining, calls)
        elif name in EXEC_TOOL_NAMES or name in BASH_TOOL_NAMES:
            self._run_exec_tool(name, args, i, remaining, calls)
        elif name in SESSION_TOOL_NAMES:
            self._run_session_tool(name, args, i, remaining, calls)
        elif name in MEMORY_TOOL_NAMES:
            self._run_memory_tool(name, args, i, remaining, calls)
        elif name in SKILL_TOOL_NAMES:
            self._run_skill_tool(args, i, remaining, calls)
        elif name in AUTHOR_TOOL_NAMES:
            self._run_author_tool(name, args, i, remaining, calls)
        elif name in JOB_TOOL_NAMES:
            self._run_job_tool(name, args, i, remaining, calls)
        elif name in GET_TOOLS_TOOL_NAMES:
            self._run_get_tools(args, i, remaining, calls)
        elif name in SPAWN_TOOL_NAMES:
            self._spawn_agent(args, i, remaining, calls)
        elif name in custom_tools():
            self._run_custom_tool(name, args, i, remaining, calls)
        else:
            remaining["sink"][i] = {
                "role": "tool", "tool_name": name,
                "content": json.dumps({"error": "unknown tool: " + name})}
            self._tool_done(remaining, calls)


    # ---- subagents (spawn_agent) -------------------------------------------

    def _spawn_agent(self, args, idx, remaining, calls):
        """Run one SUBAGENT to completion and return only its answer.

        Its own message list, its own tool rounds, its own share of the window
        — nothing it reads enters this turn's context. It reaches every tool
        through `_dispatch_tool`, the same branch the main agent uses, so the
        two cannot drift; what differs is only WHICH names its definition
        allows. Non-streaming (`stream: false`): there is no bubble to fill,
        the answer is a tool result, and one reply is far less machinery than
        an NDJSON loop that nothing would render."""
        task = str(args.get("task", "") or "").strip()
        spec = agent_spec(str(args.get("agent", "") or ""))
        if not task:
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "spawn_agent",
                "content": json.dumps({"error": "spawn_agent needs a task: say "
                                       "what the subagent should do, completely, "
                                       "since it cannot ask you."})}
            self.agentStarted.emit(spec["name"], "", "")
            self.agentDone.emit(spec["name"], False,
                                "%s — not spawned: no task given" % spec["name"])
            self._tool_done(remaining, calls)
            return
        context = str(args.get("context", "") or "").strip()
        prompt = AGENT_SYSTEM_PREFIX + "\n\n" + spec["prompt"]
        first = task if not context else (task + "\n\nContext you were given:\n"
                                          + context)
        run = {
            "name": spec["name"],
            "task": task,
            "model": spec.get("model") or self._model,
            "allowed": set(spec["tool_names"]),
            "tools": [t for t in (_tool_registry().get(n)
                                  for n in spec["tool_names"]) if t],
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": first}],
            "rounds": 0,
            "ncalls": 0,
            "used": [],
            "wrap": False,
            "idx": idx, "remaining": remaining, "calls": calls,
        }
        # The model is named only when it is NOT the parent's: a definition with
        # its own `model:` costs ollama a full unload and load (OLLAMA_MAX_LOADED
        # _MODELS=1), which is minutes of fans and nothing on screen otherwise.
        swap = run["model"] if run["model"] != self._model else ""
        self.agentStarted.emit(run["name"], task, swap)
        self._agent_post(run)

    def _agent_post(self, run):
        """POST one round of a subagent's conversation. The WRAP-UP round
        carries no tools — the same lesson the main loop learned: a model still
        calling tools when it is out of rounds, offered them again, answers
        with nothing at all."""
        payload = {"model": run["model"], "messages": run["messages"],
                   "stream": False, "options": {"num_ctx": self._num_ctx}}
        if run["tools"] and not run["wrap"]:
            payload["tools"] = run["tools"]
        req = QNetworkRequest(QUrl(OLLAMA + "/api/chat"))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        reply = self._nam.post(req, json.dumps(payload).encode("utf-8"))
        reply.finished.connect(lambda: self._agent_reply(reply, run))

    def _agent_reply(self, reply, run):
        """One subagent round came back: run its tools, or finish."""
        if not self._busy:              # the whole turn was cancelled
            reply.deleteLater()
            return
        try:
            data = bytes(reply.readAll().data())
            err = reply.error()
            err_str = reply.errorString()
        finally:
            reply.deleteLater()
        if err != QNetworkReply.NetworkError.NoError:
            self._agent_finish(run, "", error=err_str)
            return
        try:
            obj = json.loads(data or b"{}")
        except ValueError:
            self._agent_finish(run, "", error="unreadable reply from ollama")
            return
        if obj.get("error"):
            self._agent_finish(run, "", error=str(obj["error"]))
            return
        msg = obj.get("message") or {}
        content = str(msg.get("content") or "")
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls or run["wrap"]:
            self._agent_finish(run, content)
            return
        # Another round. Past the cap or out of room, run THESE calls anyway
        # and let the next post be the wrap-up: stopping on a frame that was
        # all tool calls and no prose is what returns an empty answer.
        run["rounds"] += 1
        run["ncalls"] += len(tool_calls)
        run["messages"].append({"role": "assistant", "content": content,
                                "tool_calls": tool_calls})
        if run["rounds"] >= AGENT_MAX_ROUNDS or not self._agent_room(run):
            run["wrap"] = True
        round_ = self._new_round(
            tool_calls, done=lambda sink, r=run: self._agent_round_done(r, sink))
        for i, call in enumerate(tool_calls):
            name, cargs = self._call_parts(call)
            # Into the AGENT's disclosure, not the turn's own tool list — a
            # subagent's fourteen reads are not fourteen tools the main agent
            # called, and counting them there made "tools · N" a lie about the
            # turn.
            run["used"].append(name or "tool")
            self.agentProgress.emit(run["name"], run["rounds"], name or "tool")
            if name not in run["allowed"]:
                round_["sink"][i] = {
                    "role": "tool", "tool_name": name,
                    "content": json.dumps({"error": "you were not given the "
                                           "tool %r; the tools you have are: %s"
                                           % (name, ", ".join(sorted(run["allowed"])))})}
                self._tool_done(round_, tool_calls)
                continue
            self._dispatch_tool(name, cargs, i, round_, tool_calls)

    def _agent_round_done(self, run, results):
        """A subagent's tool round is in: feed the results back and go again."""
        if not self._busy:
            return
        run["messages"] += results
        if run["wrap"]:
            run["messages"].append({"role": "user", "content": self.TOOL_CAP_PROMPT})
        self._agent_post(run)

    def _agent_room(self, run):
        """Is there context left for another subagent round? Same four-chars-a-
        token estimate `_ctx_room` uses, against the subagent's own list."""
        chars = sum(len(str(m.get("content") or "")) for m in run["messages"])
        return (chars / 4) < (self._num_ctx * AGENT_CTX_FRACTION)

    def _agent_finish(self, run, text, error=None):
        """Hand the subagent's answer back as the spawn_agent tool result."""
        answer = (text or "").strip()
        if error:
            result = {"agent": run["name"], "task": run["task"],
                      "rounds": run["rounds"], "error": error}
            if answer:
                result["partial"] = answer[:AGENT_RESULT_CHARS]
            outcome, ok = (self._agent_block(run, "failed: " + error,
                                             answer[:AGENT_RESULT_CHARS]), False)
        else:
            result = {"agent": run["name"], "task": run["task"],
                      "rounds": run["rounds"], "tool_calls": run["ncalls"],
                      "result": answer[:AGENT_RESULT_CHARS]}
            if len(answer) > AGENT_RESULT_CHARS:
                result["truncated"] = True
                result["note"] = ("the subagent's answer was longer than %d "
                                  "characters and was cut here"
                                  % AGENT_RESULT_CHARS)
            if not answer:
                result["result"] = ""
                result["note"] = ("the subagent returned nothing — it may have "
                                  "run out of rounds; try a narrower task")
            cut = " (cut)" if result.get("truncated") else ""
            outcome = self._agent_block(
                run, ("answered%s:" % cut) if answer else "returned nothing:",
                result["result"] or result.get("note", ""))
            ok = bool(answer)
        run["remaining"]["sink"][run["idx"]] = {
            "role": "tool", "tool_name": "spawn_agent",
            "content": json.dumps(result)}
        self.agentDone.emit(run["name"], ok, outcome)
        self._tool_done(run["remaining"], run["calls"])

    def _agent_block(self, run, verdict, body):
        """What a finished subagent LOOKS like in the transcript: who it was,
        what it was asked, what it cost, and what it came back with. The answer
        is in there because it is the only thing that says whether delegating
        was worth the minutes — before this the whole visible trace of a spawn
        was `agent explorer finished, 4 rounds`."""
        head = run["name"]
        if run["model"] != self._model:
            head += " · " + run["model"]
        used = []
        for t in run["used"]:                       # in call order, deduped
            if t not in used:
                used.append(t)
        cost = "%d round%s · %d tool call%s" % (
            run["rounds"], "" if run["rounds"] == 1 else "s",
            run["ncalls"], "" if run["ncalls"] == 1 else "s")
        if used:
            cost += " · " + ", ".join(used)
        lines = [head, "task: " + run["task"], cost, verdict]
        if body:
            lines.append(body)
        return "\n".join(lines)

    def _tavily_search(self, query, idx, remaining, calls):
        key = tavily_key()
        if not key:
            self.webSearchError.emit(query, "no Tavily API key configured")
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "web_search",
                "content": json.dumps({"error": "web search unavailable: no "
                                       "Tavily API key configured"})}
            self._tool_done(remaining, calls)
            return
        self.webSearchStarted.emit(query)
        body = json.dumps({
            "api_key": key,
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "max_results": self._max_results,
        }).encode("utf-8")
        req = QNetworkRequest(QUrl(TAVILY_URL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        reply = self._nam.post(req, body)
        reply.finished.connect(
            lambda: self._on_tavily(reply, query, idx, remaining, calls))

    def _on_tavily(self, reply, query, idx, remaining, calls):
        if not self._busy:            # turn was cancelled mid-search
            reply.deleteLater()
            return
        try:
            data = bytes(reply.readAll().data())
            if reply.error() != QNetworkReply.NetworkError.NoError:
                msg = reply.errorString()
                try:                  # Tavily returns a JSON error body
                    o = json.loads(data or b"{}")
                    if isinstance(o, dict) and (o.get("error") or o.get("detail")):
                        msg = str(o.get("error") or o.get("detail"))
                except ValueError:
                    pass
                self.webSearchError.emit(query, msg)
                remaining["sink"][idx] = {
                    "role": "tool", "tool_name": "web_search",
                    "content": json.dumps({"error": "web search failed: " + msg})}
                return
            obj = json.loads(data or b"{}")
            answer = obj.get("answer") or ""
            results = obj.get("results") or []
            # Fed back to the model to summarize and cite.
            remaining["sink"][idx] = {"role": "tool", "tool_name": "web_search",
                                       "content": json.dumps({
                "query": query, "answer": answer,
                "results": [{"title": r.get("title", ""), "url": r.get("url", ""),
                             "content": r.get("content", "")} for r in results]})}
            self.webSearchDone.emit(query,
                                    self._sources_markdown(answer, results),
                                    len(results))
        except (ValueError, TypeError) as e:
            self.webSearchError.emit(query, str(e))
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "web_search",
                "content": json.dumps({"error": str(e)})}
        finally:
            reply.deleteLater()
            self._tool_done(remaining, calls)

    def _search_images(self, query, idx, remaining, calls):
        """Find real direct image URLs for a subject via Tavily (include_images),
        so the model can hand a KNOWN-GOOD url to fetch_image instead of guessing
        one that 404s. Reuses the web-search disclosure signals for its UI."""
        key = tavily_key()
        if not key:
            self.webSearchError.emit(query, "no Tavily API key configured")
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "search_images",
                "content": json.dumps({"error": "image search unavailable: no "
                                       "Tavily API key configured"})}
            self._tool_done(remaining, calls)
            return
        self.webSearchStarted.emit(query)
        body = json.dumps({
            "api_key": key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": True,
            "include_image_descriptions": True,
            "max_results": 5,
        }).encode("utf-8")
        req = QNetworkRequest(QUrl(TAVILY_URL))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        reply = self._nam.post(req, body)
        reply.finished.connect(
            lambda: self._on_search_images(reply, query, idx, remaining, calls))

    def _on_search_images(self, reply, query, idx, remaining, calls):
        if not self._busy:            # turn was cancelled mid-search
            reply.deleteLater()
            return
        try:
            data = bytes(reply.readAll().data())
            if reply.error() != QNetworkReply.NetworkError.NoError:
                msg = reply.errorString()
                try:
                    o = json.loads(data or b"{}")
                    if isinstance(o, dict) and (o.get("error") or o.get("detail")):
                        msg = str(o.get("error") or o.get("detail"))
                except ValueError:
                    pass
                self.webSearchError.emit(query, msg)
                remaining["sink"][idx] = {
                    "role": "tool", "tool_name": "search_images",
                    "content": json.dumps({"error": "image search failed: " + msg})}
                return
            obj = json.loads(data or b"{}")
            images = []
            for im in (obj.get("images") or []):
                if isinstance(im, dict):
                    url = str(im.get("url", "")).strip()
                    desc = str(im.get("description", "")).strip()
                else:
                    url, desc = str(im).strip(), ""
                if url:
                    images.append({"url": url, "description": desc})
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "search_images",
                "content": json.dumps({"query": query, "images": images})
                if images else json.dumps(
                    {"query": query, "images": [],
                     "note": "no images found for this query"})}
            md = "\n".join(
                "- [" + (im["description"] or im["url"]) + "](" + im["url"] + ")"
                for im in images) or "no images found"
            self.webSearchDone.emit(query, md, len(images))
        except (ValueError, TypeError) as e:
            self.webSearchError.emit(query, str(e))
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "search_images",
                "content": json.dumps({"error": str(e)})}
        finally:
            reply.deleteLater()
            self._tool_done(remaining, calls)

    def _fetch_url(self, url, offset, idx, remaining, calls):
        """Read one web page as text. The same in-process GET fetch_image uses
        (shared QNetworkAccessManager, Qt6 follows redirects), so it runs
        wherever the window is — no executor, no host branch — and it is
        surfaced through the web-search disclosure like search_images."""
        try:
            offset = max(0, int(offset or 0))
        except (TypeError, ValueError):
            offset = 0
        u = QUrl(url)
        if u.scheme().lower() not in ("http", "https") or not u.host():
            self.webSearchError.emit(url or "(no url)", "not an http(s) URL")
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "fetch_url",
                "content": json.dumps({"error": "fetch_url takes an absolute "
                                       "http:// or https:// URL"})}
            self._tool_done(remaining, calls)
            return
        self.webSearchStarted.emit(url)
        req = QNetworkRequest(u)
        # A default Qt UA gets a bot wall on a fair number of sites; naming a
        # real browser shape is what makes the tool actually able to READ them.
        req.setRawHeader(b"User-Agent",
                         b"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         b"(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
        req.setRawHeader(b"Accept", b"text/html,application/xhtml+xml,"
                                    b"application/json;q=0.9,text/plain;q=0.8,*/*;q=0.5")
        reply = self._nam.get(req)
        reply.finished.connect(
            lambda: self._on_fetch_url(reply, url, offset, idx, remaining, calls))

    def _on_fetch_url(self, reply, url, offset, idx, remaining, calls):
        if not self._busy:              # turn was cancelled mid-fetch
            reply.deleteLater()
            return
        try:
            data = bytes(reply.readAll().data())
            if reply.error() != QNetworkReply.NetworkError.NoError:
                msg = reply.errorString()
                self.webSearchError.emit(url, msg)
                remaining["sink"][idx] = {
                    "role": "tool", "tool_name": "fetch_url",
                    "content": json.dumps({"error": "fetch failed: " + msg,
                                           "url": url})}
                return
            ctype = str(reply.header(
                QNetworkRequest.KnownHeaders.ContentTypeHeader) or "")
            final = reply.url().toString() or url
            if len(data) > FETCH_URL_MAX_BYTES:
                data = data[:FETCH_URL_MAX_BYTES]
            low = ctype.lower()
            # Binary is refused rather than dumped as mojibake — the same
            # honesty the file tools' binary refusal carries. An image URL is
            # named for what it is, so the model reaches for fetch_image.
            if low.startswith("image/"):
                result = {"error": "that URL is an image, not a page — use "
                                   "fetch_image to show it", "url": final,
                          "content_type": ctype}
                self.webSearchError.emit(url, "not a page (" + ctype + ")")
            elif (low.startswith("application/") and "json" not in low
                  and "xml" not in low and "javascript" not in low) \
                    or low.startswith(("audio/", "video/", "font/")):
                result = {"error": "not text: " + (ctype or "unknown type"),
                          "url": final, "content_type": ctype}
                self.webSearchError.emit(url, "not text (" + ctype + ")")
            else:
                body = data.decode("utf-8", "replace")
                title = ""
                if "html" in low or (not ctype and body.lstrip()[:1] == "<"):
                    parser = _PageText()
                    try:
                        parser.feed(body)
                        parser.close()
                    except Exception:            # a malformed page still gives
                        pass                     # us whatever it parsed so far
                    text, title = parser.text(), parser.title
                else:
                    text = body.strip()
                total = len(text)
                page = text[offset:offset + FETCH_URL_CHARS]
                result = {"url": final, "title": title,
                          "content_type": ctype or "unknown",
                          "chars_total": total, "offset": offset,
                          "text": page}
                if offset + len(page) < total:
                    result["truncated"] = True
                    result["next_offset"] = offset + len(page)
                self.webSearchDone.emit(
                    url, "- [" + (title or final) + "](" + final + ")", 1)
            remaining["sink"][idx] = {"role": "tool", "tool_name": "fetch_url",
                                       "content": json.dumps(result)}
        except (ValueError, TypeError) as e:
            self.webSearchError.emit(url, str(e))
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "fetch_url",
                "content": json.dumps({"error": str(e), "url": url})}
        finally:
            reply.deleteLater()
            self._tool_done(remaining, calls)

    def _call_api(self, args, idx, remaining, calls):
        """Query a JSON API and hand back projected rows. The same in-process
        GET fetch_url uses (shared QNetworkAccessManager, Qt6 follows
        redirects), so it runs wherever the window is — no executor, no host
        branch — and it is surfaced through the web-search disclosure."""
        def fail(label, msg):
            self.webSearchError.emit(label or "call_api", msg)
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "call_api",
                "content": json.dumps({"error": msg})}
            self._tool_done(remaining, calls)

        site = str(args.get("site", "") or "").strip().lower()
        method = str(args.get("method", "GET") or "GET").strip().upper()
        if method not in ("GET", "HEAD"):
            fail(site, "call_api is read-only: GET and HEAD only, not " + method)
            return
        if site and site not in API_SITES:
            fail(site, "unknown site: " + site + " — known sites are "
                 + ", ".join(sorted(API_SITES)) + ", or give an absolute url")
            return
        spec = API_SITES.get(site, {})
        params = args.get("params")
        params = dict(params) if isinstance(params, dict) else {}
        fields = args.get("fields")
        fields = list(fields) if isinstance(fields, list) else spec.get("fields")
        select = args.get("select") or spec.get("select") or ""
        try:
            row_offset = max(0, int(args.get("offset") or 0))
        except (TypeError, ValueError):
            row_offset = 0

        if site:
            path = str(args.get("path", "") or spec["path"])
            if not path.startswith("/"):
                path = "/" + path
            u = QUrl(spec["base"] + path)
            merged = dict(spec.get("params", {}))
            merged.update(params)
            params = merged
            creds = api_credentials(site)
            # A site KNOWN to refuse anonymous requests is refused here rather
            # than by its own 401/403 — the round trip buys nothing, and the
            # model gets the thing it can act on: what to put where.
            if spec.get("auth") and not creds:
                want = spec["auth"].get("params") or spec["auth"].get("basic") or []
                fail(site, site + " needs credentials: put {\"" + site
                     + "\": {\"" + ("params" if spec["auth"].get("params")
                                    else "basic") + "\": "
                     + json.dumps(want) + "}} in " + API_KEYS_PATH
                     + " (values, not these placeholders) — tell him that, do "
                       "not guess a key")
                return
        else:
            raw = str(args.get("url", "") or "").strip()
            u = QUrl(raw)
            if u.scheme().lower() not in ("http", "https") or not u.host():
                fail(raw, "call_api takes a known `site` or an absolute "
                          "http:// or https:// `url`")
                return
            creds = api_credentials(str(args.get("auth", "") or "").strip()) \
                if args.get("auth") else {}

        q = QUrlQuery(u)
        for k, v in params.items():
            if v is None:
                continue
            q.removeAllQueryItems(str(k))
            q.addQueryItem(str(k), str(v))
        for k, v in (creds.get("params") or {}).items():
            q.removeAllQueryItems(str(k))
            q.addQueryItem(str(k), str(v))
        u.setQuery(q)
        safe = _api_safe_url(u.toString())

        req = QNetworkRequest(u)
        req.setRawHeader(b"Accept", b"application/json,text/plain;q=0.8,*/*;q=0.5")
        for k, v in (spec.get("headers") or {}).items():
            req.setRawHeader(str(k).encode(), str(v).encode())
        if not (spec.get("headers") or {}).get("User-Agent"):
            # NOT fetch_url's browser UA — the opposite rule holds here.
            # Measured 2026-08-22: danbooru's JSON API answers that Chrome
            # string with 403 and this one with 200. An API wants a named
            # client; a page wants a browser.
            req.setRawHeader(b"User-Agent", API_USER_AGENT)
        for k, v in (creds.get("headers") or {}).items():
            req.setRawHeader(str(k).encode(), str(v).encode())
        basic = creds.get("basic")
        if isinstance(basic, (list, tuple)) and len(basic) == 2:
            token = base64.b64encode(
                (str(basic[0]) + ":" + str(basic[1])).encode()).decode()
            req.setRawHeader(b"Authorization", b"Basic " + token.encode())

        self.webSearchStarted.emit((site + ": " if site else "") + safe)
        reply = self._nam.head(req) if method == "HEAD" else self._nam.get(req)
        reply.finished.connect(
            lambda: self._on_call_api(reply, safe, site, fields, select,
                                      row_offset, method, idx, remaining, calls))

    def _on_call_api(self, reply, safe, site, fields, select, row_offset,
                     method, idx, remaining, calls):
        if not self._busy:              # turn was cancelled mid-call
            reply.deleteLater()
            return
        try:
            data = bytes(reply.readAll().data())
            status = reply.attribute(
                QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error() != QNetworkReply.NetworkError.NoError:
                msg = reply.errorString()
                # A booru answers an auth failure with a 401/403 body, and
                # "which key is missing" is the one thing worth naming.
                extra = ""
                if status in (401, 403) and site and not api_credentials(site):
                    extra = (" — no keyring entry for " + site + " in "
                             + API_KEYS_PATH)
                self.webSearchError.emit(safe, msg)
                remaining["sink"][idx] = {
                    "role": "tool", "tool_name": "call_api",
                    "content": json.dumps({"error": "request failed: " + msg + extra,
                                           "status": status, "url": safe})}
                return
            ctype = str(reply.header(
                QNetworkRequest.KnownHeaders.ContentTypeHeader) or "")
            if method == "HEAD":
                result = {"url": safe, "status": status,
                          "content_type": ctype or "unknown"}
                self.webSearchDone.emit(safe, "- [" + safe + "](" + safe + ")", 1)
                remaining["sink"][idx] = {"role": "tool", "tool_name": "call_api",
                                           "content": json.dumps(result)}
                return
            if len(data) > API_MAX_BYTES:
                data = data[:API_MAX_BYTES]
            body = data.decode("utf-8", "replace").strip()
            low = ctype.lower()
            if low.startswith(("image/", "audio/", "video/", "font/")):
                result = {"error": "not JSON: " + ctype, "url": safe}
                self.webSearchError.emit(safe, "not JSON (" + ctype + ")")
            else:
                try:
                    doc = json.loads(body) \
                        if ("json" in low or body[:1] in "{[") else None
                except ValueError:
                    doc = None
                if doc is None:
                    # Not JSON at all — hand back the capped text rather than
                    # pretending (docs/DESIGN.md §10), and say what it was.
                    result = {"url": safe, "content_type": ctype or "unknown",
                              "note": "the response was not JSON; raw text follows",
                              "text": body[:API_CHARS]}
                    if len(body) > API_CHARS:
                        result["truncated"] = True
                else:
                    result = self._api_project(doc, safe, ctype, fields, select,
                                               row_offset)
                self.webSearchDone.emit(safe, "- [" + (site or safe) + "]("
                                        + safe + ")", 1)
            remaining["sink"][idx] = {"role": "tool", "tool_name": "call_api",
                                       "content": json.dumps(result)}
        except (ValueError, TypeError) as e:
            self.webSearchError.emit(safe, str(e))
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": "call_api",
                "content": json.dumps({"error": str(e), "url": safe})}
        finally:
            reply.deleteLater()
            self._tool_done(remaining, calls)

    @staticmethod
    def _api_project(doc, safe, ctype, fields, select, row_offset):
        """The parsed response reduced to what was asked for: the result LIST
        located, each row projected to `fields`, and the whole thing capped by
        DROPPING ROWS rather than by cutting a JSON document in half — a
        half-serialized row is unreadable to the model, a short list is not."""
        rows = _api_dig(doc, select) if select else doc
        if rows is None and select:
            return {"url": safe, "error": "no list at select path: " + select,
                    "keys": sorted(doc)[:40] if isinstance(doc, dict) else None}
        if not isinstance(rows, list):
            text = json.dumps(rows if rows is not None else doc,
                              ensure_ascii=False)
            out = {"url": safe, "content_type": ctype or "unknown",
                   "json": text[:API_CHARS]}
            if len(text) > API_CHARS:
                out["truncated"] = True
                out["note"] = ("the response is not a list, so it could not be "
                               "paged — name `select` or `fields` to narrow it")
            return out
        total = len(rows)
        window = rows[row_offset:row_offset + API_MAX_ROWS]
        keep = None if (not fields or "*" in fields) else fields
        picked = []
        for row in window:
            if keep is None or not isinstance(row, dict):
                picked.append(row)
            else:
                picked.append({f: _api_dig(row, f) for f in keep})
        # Cap by dropping whole rows off the end.
        while picked and len(json.dumps(picked, ensure_ascii=False)) > API_CHARS:
            picked.pop()
        out = {"url": safe, "count_returned": len(picked), "count_total": total,
               "offset": row_offset, "rows": picked}
        if not picked and window:
            out["error"] = ("even one row is over the size cap — ask for fewer "
                            "`fields`")
        if row_offset + len(picked) < total:
            out["truncated"] = True
            out["next_offset"] = row_offset + len(picked)
        if keep is not None:
            out["fields"] = keep
        return out

    def _tool_done(self, remaining, calls):
        """One call of a round finished. When the LAST one does, the round is
        handed on: to whatever spawned it if it set `done` (a subagent's inner
        loop), otherwise to the chat loop below."""
        remaining["n"] -= 1
        if remaining["n"] > 0 or not self._busy:
            return
        finish = remaining.get("done")
        if finish is not None:
            finish([tr for tr in remaining["sink"] if tr is not None])
            return
        for tr in remaining["sink"]:
            if tr is not None:
                self._messages.append(tr)
        # Pictures `view_image` fetched this round: ollama carries image bytes
        # on a message, not in a tool result, so they ride a user message of
        # their own — the same `images` field a dropped attachment uses.
        if self._pending_vision:
            self._messages.append(
                {"role": "user",
                 "content": ("[the image(s) you asked to look at, attached]"),
                 "images": self._pending_vision})
            self._pending_vision = []
        # A new round: the segment just finished is closed and QML opens a
        # fresh bubble for what comes next (see `roundStarted`).
        self._row_urls = set()          # a fresh bubble carries no pictures yet
        self.roundStarted.emit(self._rounds + 1)
        # The wrap-up round (see `_on_finished`): say why there are no tools.
        if self._no_tools:
            self._messages.append({"role": "user",
                                   "content": self.TOOL_CAP_PROMPT})
        self._post_chat()

    @staticmethod
    def _sources_markdown(answer, results):
        """The sources disclosure body: Tavily's own answer, then a themed-link
        list of the hits (docs/DESIGN.md §2 — drawn through MarkdownText)."""
        lines = []
        if answer:
            lines.append(answer.strip())
            lines.append("")
        for r in results:
            title = (r.get("title") or r.get("url") or "untitled").strip()
            url = (r.get("url") or "").strip()
            lines.append("- [" + title + "](" + url + ")" if url
                         else "- " + title)
        return "\n".join(lines)

    # ---- the image-fetch tool (in-process download, rendered inline) ----

    @staticmethod
    def _image_error(url, reason):
        """The one failure shape, split for its two audiences: the entry QML
        draws as a crit line, and the tool result the model reads (§10 — the
        failure is reported to both, never silently dropped)."""
        return ({"ok": False, "url": url, "error": reason},
                {"error": "image fetch failed: " + reason})

    #: Boorus address an image by the file's own md5, and a model that retypes
    #: one from memory gets it subtly wrong — `12a90ec8d770cc4898c17bece1ee561`
    #: (31 chars) and `45bf9a3erm88cd10126904ca995c7` (not even hex) both went
    #: out on 2026-08-22 and both 404'd. The shape is checkable before any
    #: request, and the refusal can say what to do instead, which a bare 404
    #: cannot.
    BOORU_MD5_HOSTS = ("cdn.donmai.us", "konachan.com", "konachan.net",
                       "img3.gelbooru.com", "video-cdn.donmai.us",
                       "static1.e621.net", "static1.e926.net")

    @classmethod
    def _booru_url_fault(cls, url):
        """"That url cannot be right", before it is sent — or "" if it may be."""
        try:
            host = QUrl(url).host().lower()
        except (ValueError, TypeError):
            return ""
        if host not in cls.BOORU_MD5_HOSTS:
            return ""
        if re.search(r"/[0-9a-f]{32}(?:[./]|$)", url, re.I):
            return ""
        # Only complain when there IS something md5-shaped and it is wrong;
        # these hosts serve other paths too (sample/, preview/, thumbnails).
        m = re.search(r"/([0-9A-Za-z]{24,40})(?:\.[a-z0-9]+)?(?:[/?#]|$)", url)
        if not m:
            return ""
        tok = m.group(1)
        return ("that URL's md5 is %r — %d characters%s, and these sites need "
                "exactly 32 hex. It is a URL typed from memory, not a real one. "
                "Do not retype image URLs: copy `file_url` VERBATIM out of a "
                "call_api / search_images result, or search again."
                % (tok, len(tok),
                   "" if re.fullmatch(r"[0-9a-f]+", tok, re.I)
                   else " and not hexadecimal"))

    def _emit_image(self, entry):
        """Hand ONE picture to QML, and remember it.

        Every entry goes through here so two ledgers stay true: `_image_entries`
        (what this turn has already downloaded, by URL) and `_row_urls` (what is
        already on the bubble being written). `_attach_typed_images` needs both
        to put a picture the model NAMES under the words that name it, without
        fetching it twice or drawing it twice on one bubble.
        """
        if isinstance(entry, dict):
            url = str(entry.get("url") or "")
            if url:
                self._row_urls.add(url)
                if entry.get("ok"):
                    self._image_entries[url] = entry
        self.imageFetchResult.emit(json.dumps(entry))

    def _image_failed(self, url, reason, idx, remaining, calls):
        """Fail one image the same way for both audiences, tool or not."""
        entry, result = self._image_error(url, reason)
        self._emit_image(entry)
        if idx is None:
            self._typed_image_done(remaining)
            return
        remaining["sink"][idx] = {"role": "tool", "tool_name": "fetch_image",
                                   "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    def _fetch_image(self, url, alt, idx, remaining, calls):
        """Download one image by URL and hand the local path to QML to render.

        A GET on the shared QNAM (Qt6 follows redirects by default), validated on
        completion in `_on_image`. A URL that is not http(s) — or one whose booru
        md5 is plainly mistyped — never reaches the network: it is failed
        immediately, still through the same contract so QML and the model both
        see the refusal.

        `idx` is the tool call this fetch answers, or None when the model TYPED
        the image into its reply instead of calling the tool
        (`_attach_typed_images`) — then there is no tool result to write, only
        the picture."""
        if url:
            self._images_shown.add(url)
        if not url or not re.match(r"^https?://", url, re.I):
            self.imageFetchStarted.emit(url or "(no url)")
            self._image_failed(url, "not a valid http(s) image URL",
                               idx, remaining, calls)
            return
        fault = self._booru_url_fault(url)
        if fault:
            self.imageFetchStarted.emit(url)
            self._image_failed(url, fault, idx, remaining, calls)
            return
        self.imageFetchStarted.emit(url)
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                      "oracle-chatter/1.0")
        reply = self._nam.get(req)
        reply.finished.connect(
            lambda: self._on_image(reply, url, alt, idx, remaining, calls))

    def _on_image(self, reply, url, alt, idx, remaining, calls):
        """Validate the download, save it locally, and feed both audiences.

        Three honest failure modes (docs/DESIGN.md §10): a network/HTTP error, a
        body that does not decode as an image (a web page, a 404 HTML), and a
        body too large. Success saves the bytes under IMAGES_ROOT and returns the
        path plus real pixel dimensions for QML to size the frame."""
        if not self._busy:            # turn was cancelled mid-fetch
            reply.deleteLater()
            return
        try:
            data = bytes(reply.readAll().data())
            ctype = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader)
                        or "").split(";")[0].strip().lower()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                reason = reply.errorString()
                # A 404 on an image URL is nearly always a URL the model typed
                # from memory rather than copied. Say so in the result, so the
                # retry it gets is a search and not another guess.
                if "404" in reason:
                    reason += (" — if you typed this URL from memory, do not: "
                               "copy `file_url` verbatim out of a call_api / "
                               "search_images result, or search again")
                entry, result = self._image_error(url, reason)
            elif len(data) > IMAGE_MAX_BYTES:
                entry, result = self._image_error(
                    url, "image too large (%d MB, limit %d MB)"
                    % (len(data) // (1024 * 1024),
                       IMAGE_MAX_BYTES // (1024 * 1024)))
            else:
                img = QImage()
                if not img.loadFromData(data) or img.isNull():
                    reason = "server did not return a decodable image"
                    if ctype:
                        reason += " (content-type: %s)" % ctype
                    entry, result = self._image_error(url, reason)
                else:
                    path = self._save_image(data, url, ctype)
                    if not path:
                        entry, result = self._image_error(
                            url, "could not save the image locally")
                    else:
                        entry = {"ok": True, "url": url, "path": path, "alt": alt,
                                 "w": img.width(), "h": img.height()}
                        result = {"ok": True, "url": url, "width": img.width(),
                                  "height": img.height(),
                                  "note": ("Image downloaded and now shown inline "
                                           "in the chat for the user to see.")}
        except (ValueError, TypeError, OSError) as e:
            entry, result = self._image_error(url, str(e))
        finally:
            reply.deleteLater()
        self._emit_image(entry)
        if idx is None:
            self._typed_image_done(remaining)
            return
        remaining["sink"][idx] = {"role": "tool", "tool_name": "fetch_image",
                                   "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    @staticmethod
    def _save_image(data, url, ctype):
        """Write the bytes under IMAGES_ROOT, returning the absolute path or "".
        Content-addressed by URL so re-fetching the same image reuses one file;
        the extension is derived from the content-type (else the URL suffix, else
        .img) and is cosmetic — QML's Image sniffs the data itself."""
        ext = IMAGE_EXT.get(ctype, "")
        if not ext:
            m = re.search(r"\.(png|jpe?g|gif|webp|bmp|svg|tiff?|ico|avif)(?:$|[?#])",
                          url, re.I)
            ext = ("." + m.group(1).lower()) if m else ".img"
        name = hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:16] + ext
        try:
            os.makedirs(IMAGES_ROOT, exist_ok=True)
            path = os.path.join(IMAGES_ROOT, name)
            with open(path, "wb") as f:
                f.write(data)
            return path
        except OSError:
            return ""

    # ---- the models themselves (manage_models, over ollama's own API) ----

    def _run_model_tool(self, args, idx, remaining, calls):
        """List, describe, pull or remove an ollama model.

        Every one of these is an HTTP call to the daemon this app already talks
        to — no shell, so no runner caps to trip over, and a `pull` STREAMS, so
        the download is watched rather than waited on."""
        a = args if isinstance(args, dict) else {}
        action = str(a.get("action") or "list").strip().lower()
        model = str(a.get("model") or "").strip()

        def answer(result, ok=True, line=""):
            remaining["sink"][idx] = {"role": "tool", "tool_name": "manage_models",
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(line or ("models: "
                                            + str(result.get("error", ""))), ok)
            self._tool_done(remaining, calls)

        if action in ("show", "pull", "remove") and not model:
            self.fileToolStarted.emit("models")
            answer({"error": action + " needs a model name"}, False)
            return
        if action == "list":
            self.fileToolStarted.emit("listing models")
            self._model_api("/api/tags", None, "GET", lambda ok, obj:
                            self._model_list_done(ok, obj, answer))
            return
        if action == "show":
            self.fileToolStarted.emit("model: " + model)
            self._model_api("/api/show", {"model": model}, "POST", lambda ok, obj:
                            answer(self._model_show(obj) if ok
                                   else {"error": self._model_why(obj)}, ok,
                                   "model · " + model))
            return
        if action == "remove":
            if not a.get("confirm"):
                self.fileToolStarted.emit("models")
                answer({"error": "removing %s deletes his weights — ask him "
                                 "first, then call again with confirm: true"
                                 % model}, False)
                return
            self.fileToolStarted.emit("removing " + model)
            self._model_api("/api/delete", {"model": model}, "DELETE",
                            lambda ok, obj: answer(
                                {"ok": True, "removed": model} if ok
                                else {"error": self._model_why(obj)}, ok,
                                ("removed " + model) if ok else ""))
            return
        if action == "pull":
            self._model_pull(model, answer)
            return
        self.fileToolStarted.emit("models")
        answer({"error": "unknown action: " + action}, False)

    def _model_api(self, path, payload, verb, cb):
        """One ollama API call, JSON in and out. `cb(ok, obj)`."""
        req = QNetworkRequest(QUrl(OLLAMA + path))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        body = json.dumps(payload or {}).encode("utf-8")
        if verb == "GET":
            reply = self._nam.get(req)
        elif verb == "DELETE":
            reply = self._nam.sendCustomRequest(req, b"DELETE", body)
        else:
            reply = self._nam.post(req, body)

        def done():
            try:
                raw = bytes(reply.readAll().data()).decode("utf-8", "replace")
                err = reply.error() != QNetworkReply.NetworkError.NoError
                why = reply.errorString()
            except RuntimeError:
                return
            reply.deleteLater()
            try:
                obj = json.loads(raw or "{}")
            except ValueError:
                obj = {"error": raw.strip()[:400] or why}
            if err and not isinstance(obj, dict):
                obj = {"error": why}
            cb(not err, obj if isinstance(obj, dict) else {"data": obj})

        reply.finished.connect(done)

    @staticmethod
    def _model_why(obj):
        """ollama's own complaint, or something honest in its place."""
        if isinstance(obj, dict):
            for key in ("error", "message"):
                if obj.get(key):
                    return str(obj[key])[:400]
        return "the ollama daemon refused that"

    @staticmethod
    def _model_list_done(ok, obj, answer):
        if not ok:
            answer({"error": Ollama._model_why(obj)}, False)
            return
        out = []
        for m in (obj.get("models") or []):
            det = m.get("details") or {}
            out.append({"name": m.get("name") or m.get("model") or "",
                        "size_gb": round((m.get("size") or 0) / (1 << 30), 1),
                        "family": det.get("family") or "",
                        "parameters": det.get("parameter_size") or "",
                        "quantization": det.get("quantization_level") or "",
                        "modified": str(m.get("modified_at") or "")[:19]})
        out.sort(key=lambda r: -r["size_gb"])
        answer({"ok": True, "count": len(out), "models": out}, True,
               "models · %d installed" % len(out))

    @staticmethod
    def _model_show(obj):
        info = obj.get("model_info") or {}
        ctx = next((v for k, v in info.items() if k.endswith(".context_length")), 0)
        det = obj.get("details") or {}
        return {"ok": True, "parameters": det.get("parameter_size") or "",
                "quantization": det.get("quantization_level") or "",
                "family": det.get("family") or "",
                "context_length": ctx,
                "capabilities": obj.get("capabilities") or [],
                "system": (obj.get("system") or "")[:500]}

    def _model_pull(self, model, answer):
        """Pull one model, streaming ollama's progress into the row.

        The disk is checked FIRST: the weights land on `/`, which runs fairly
        full, and finding that out 18 GB in is not a check. Progress arrives as
        NDJSON — the same shape the chat stream uses — and goes to the same live
        tail a running program writes to, so a 20-minute download looks like
        work rather than like a hang."""
        free = 0
        try:
            free = shutil.disk_usage(os.path.expanduser("~")).free
        except OSError:
            pass
        if free and free < MODEL_DISK_FLOOR:
            answer({"error": "only %.1f GB free on this disk — a model will not "
                             "fit, and it is his root filesystem"
                             % (free / (1 << 30))}, False)
            return
        self.fileToolStarted.emit("pulling " + model)
        self.execStarted.emit("pulling " + model)
        req = QNetworkRequest(QUrl(OLLAMA + "/api/pull"))
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                      "application/json")
        req.setTransferTimeout(0)          # a 20 GB pull is not a timeout
        reply = self._nam.post(req, json.dumps(
            {"model": model, "stream": True}).encode("utf-8"))
        state = {"buf": b"", "last": "", "pct": -1, "err": ""}

        def pump():
            try:
                state["buf"] += bytes(reply.readAll().data())
            except RuntimeError:
                return
            while b"\n" in state["buf"]:
                line, state["buf"] = state["buf"].split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if obj.get("error"):
                    state["err"] = str(obj["error"])[:400]
                    continue
                status = str(obj.get("status") or "")
                total, got = obj.get("total") or 0, obj.get("completed") or 0
                if total:
                    pct = int(got * 100 / total)
                    if pct != state["pct"]:
                        state["pct"] = pct
                        self.execOutput.emit(
                            "%s  %d%%  (%.1f of %.1f GB)\n"
                            % (status, pct, got / (1 << 30), total / (1 << 30)))
                elif status and status != state["last"]:
                    self.execOutput.emit(status + "\n")
                state["last"] = status

        def done():
            pump()
            try:
                bad = reply.error() != QNetworkReply.NetworkError.NoError
                why = reply.errorString()
            except RuntimeError:
                return
            reply.deleteLater()
            self.execFinished.emit()
            if state["err"] or bad:
                answer({"error": state["err"] or why}, False,
                       "pull failed: " + (state["err"] or why)[:120])
                return
            answer({"ok": True, "model": model,
                    "note": ("Pulled and ready. He can pick it in the model "
                             "selector; you are still the model you were.")},
                   True, "pulled " + model)

        reply.readyRead.connect(pump)
        reply.finished.connect(done)
        QTimer.singleShot(MODEL_PULL_MS, lambda: reply.abort()
                          if reply is not None else None)

    # ---- his own tools (a directory of manifests, see CUSTOM_TOOLS_ROOT) ----

    def _run_custom_tool(self, name, args, idx, remaining, calls):
        """Run one of HIS tools: arguments as JSON on stdin, stdout is the
        answer.

        The same async QProcess idiom as every executor here, and the same
        honesty on failure — a non-zero exit comes back as an error carrying
        what the program printed on stderr, so the model can tell him which of
        his scripts broke and how (docs/DESIGN.md §10). Output is capped like
        any other tool result; a program that never exits is killed at its own
        `timeout` and says so."""
        spec = custom_tools().get(name)
        if not spec:
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": name,
                "content": json.dumps({"error": "that tool is no longer installed"})}
            self._tool_done(remaining, calls)
            return
        self.fileToolStarted.emit("running your tool: " + name)
        proc = QProcess(self)
        self._procs.append(proc)
        state = {"done": False, "timeout": False}

        def answer(result, ok, line):
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(line, ok)
            self._tool_done(remaining, calls)

        def finished(*_):
            if state["done"]:
                return
            state["done"] = True
            if proc in self._procs:
                self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
                err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            if state["timeout"]:
                answer({"error": "%s ran past its %g second timeout and was killed"
                        % (name, spec["timeout"])}, False,
                       name + ": timed out")
                return
            out = out[:CUSTOM_MAX_BYTES]
            if rc != 0:
                why = (err.strip().splitlines() or ["exit %d" % rc])[-1]
                answer({"error": why, "exit_code": rc,
                        "stdout": out.strip()[:2000]}, False,
                       "%s: %s" % (name, why[:120]))
                return
            try:
                parsed = json.loads(out or "null")
            except ValueError:
                parsed = None
            result = (parsed if isinstance(parsed, (dict, list))
                      else {"ok": True, "output": out.strip()})
            answer(result, True, name + " ok")

        def failed(err):
            if state["done"] or err != QProcess.ProcessError.FailedToStart:
                return
            state["done"] = True
            if proc in self._procs:
                self._procs.remove(proc)
            proc.deleteLater()
            answer({"error": "could not run %s (%s)" % (name, spec["prog"])},
                   False, name + ": could not run")

        def expire():
            if state["done"]:
                return
            state["timeout"] = True
            try:
                proc.kill()
            except RuntimeError:
                pass

        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        QTimer.singleShot(int(spec["timeout"] * 1000), expire)
        proc.setWorkingDirectory(os.path.dirname(spec["prog"]) or ".")
        proc.start(spec["prog"], [])
        proc.write(json.dumps(args if isinstance(args, dict) else {})
                   .encode("utf-8"))
        proc.closeWriteChannel()

    # ---- media playback (control_media, over MPRIS + the PipeWire mixer) ----

    @staticmethod
    def _player_argv(rest, target=None):
        """`playerctl -p <name> …` for one verb. The name, and the binary, are
        both overridable — which is how the harness drives a STUB and never his
        player, playing music a foot away while the tests run (root AGENTS.md).

        `target` is what he named, if he named one; otherwise `MPRIS_NAME`,
        which is a FALLBACK LIST (`player,%any`) rather than one bus name.
        """
        name = str(target or "").strip() or MPRIS_NAME
        return [PLAYERCTL, "-p", name] + list(rest)

    #: One line carrying everything the model is told, so a status costs ONE
    #: process rather than nine property reads. (QtDBus was the obvious route
    #: and is a dead end here: PySide cannot demarshal MPRIS's `a{sv}` Metadata
    #: — `QDBusArgument.asVariant()` returns null and the title comes back
    #: empty, measured 2026-08-23 against the real player. playerctl is a real
    #: MPRIS client and hands back text.)
    PLAYER_FORMAT = ("{{status}}\t{{title}}\t{{artist}}\t{{album}}\t"
                     "{{mpris:length}}\t{{position}}\t{{volume}}\t"
                     "{{shuffle}}\t{{loop}}\t{{playerName}}")

    def _pctl(self, rest, cb, target=None):
        """Run one playerctl call and hand (rc, stdout, stderr) to `cb`.

        Async on the file tools' QProcess idiom: these answer in milliseconds,
        but a player that has just died makes D-Bus wait, and the window must
        not."""
        proc = QProcess(self)
        self._procs.append(proc)
        done = {"n": False}

        def finished(*_):
            if done["n"]:
                return
            done["n"] = True
            if proc in self._procs:
                self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
                err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            cb(rc, out, err)

        def failed(err):
            if done["n"] or err != QProcess.ProcessError.FailedToStart:
                return
            done["n"] = True
            if proc in self._procs:
                self._procs.remove(proc)
            proc.deleteLater()
            cb(127, "", "playerctl is not installed here")

        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        argv = self._player_argv(rest, target)
        proc.start(argv[0], argv[1:])

    @staticmethod
    def _player_parse(line):
        """PLAYER_FORMAT's one line -> the status the model gets back."""
        f = (line.rstrip("\n").split("\t") + [""] * 10)[:10]

        def secs(us):
            try:
                return round(float(us) / 1_000_000, 1)
            except (TypeError, ValueError):
                return 0.0

        out = {"ok": True, "playing": f[0] or "Stopped", "title": f[1],
               "artist": f[2], "album": f[3],
               "duration_seconds": secs(f[4]), "position_seconds": secs(f[5]),
               "shuffle": f[7].strip().lower() in ("true", "on", "1"),
               "loop": f[8] or "None",
               "player": f[9] or ""}
        # The PLAYER's own volume, which for his `player` is 1.0 for ever
        # because it exposes none — reported as what it is, and never as the
        # answer to "how loud is it" (that is `system_volume`, added by
        # `_mixer`). docs/DESIGN.md §10: a number that means nothing is not
        # dressed up as one that does.
        try:
            out["player_volume"] = int(round(float(f[6]) * 100))
        except (TypeError, ValueError):
            pass
        return out

    # ---- the system mixer (PipeWire) ----

    def _mixer(self, cb):
        """Read the machine's volume and mute state. `wpctl get-volume` prints
        `Volume: 0.55` (plus ` [MUTED]`), so one call answers both."""
        proc = QProcess(self)
        self._procs.append(proc)

        def done():
            try:
                out = bytes(proc.readAllStandardOutput().data()).decode(
                    "utf-8", "replace")
                rc = proc.exitCode()
            except RuntimeError:
                return
            if proc in self._procs:
                self._procs.remove(proc)
            proc.deleteLater()
            if rc != 0:
                cb({})
                return
            m = re.search(r"([\d.]+)", out)
            vol = {}
            if m:
                try:
                    vol["system_volume"] = int(round(float(m.group(1)) * 100))
                except ValueError:
                    pass
            vol["muted"] = "MUTED" in out.upper()
            cb(vol)

        proc.finished.connect(done)
        proc.errorOccurred.connect(lambda *_: cb({}))
        proc.start(WPCTL, ["get-volume", AUDIO_SINK])

    def _mixer_set(self, args, cb):
        """One `wpctl set-…` call; `cb(ok)` when it is done.

        A HARNESS NEVER MOVES HIS VOLUME. Under `--selftest` this refuses
        unless `$ORACLE_WPCTL` has been pointed at a stub — the same shape as
        `Backend._systemctl`'s refusal, and for the same reason: he is
        listening while the tests run (root AGENTS.md), and a test that turns
        the music down is a bug in the test.
        """
        if SELFTEST and not os.environ.get("ORACLE_WPCTL"):
            cb(False)
            return
        proc = QProcess(self)
        self._procs.append(proc)

        def done():
            try:
                rc = proc.exitCode()
            except RuntimeError:
                return
            if proc in self._procs:
                self._procs.remove(proc)
            proc.deleteLater()
            cb(rc == 0)

        proc.finished.connect(done)
        proc.errorOccurred.connect(lambda *_: cb(False))
        proc.start(WPCTL, list(args))

    @staticmethod
    def _music_argv():
        """The command that runs one library/queue op where the MUSIC is.

        Same host branch as the file and code executors: local on `top`, over
        the tunnel's ssh master from `book` — the library database and the
        player's queue socket are both top's, and a book window driving its own
        (absent) player would be a tool that silently does nothing.
        `$ORACLE_MUSIC` replaces the script, which is how the harness drives a
        fake library and a fake socket instead of his."""
        script = os.environ.get("ORACLE_MUSIC", "").strip() or MUSIC_SCRIPT
        if ON_BOOK:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            return argv + [host, "python3", shlex.quote(script)]
        return [sys.executable, script]

    def _music_call(self, req, cb):
        """One library op, async, feeding `cb(result)` the parsed answer."""
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            cb(self._fs_result(out, err, rc))

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)   # surfaced through finished
        argv = self._music_argv()
        proc.start(argv[0], argv[1:])
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()

    def _run_music_tool(self, args, idx, remaining, calls):
        """Search the library and hand back rows, each carrying its `path` —
        which is the whole point: a path is what control_media can put on."""
        a = args if isinstance(args, dict) else {}
        action = str(a.get("action") or "search").strip().lower()
        req = {"op": action,
               "q": str(a.get("query") or ""),
               "artist": str(a.get("artist") or ""),
               "album": str(a.get("album") or ""),
               "genre": str(a.get("genre") or ""),
               "sort": str(a.get("sort") or ""),
               "favorites_only": bool(a.get("favorites_only")),
               "min_rating": a.get("min_rating") or 0,
               "limit": a.get("limit") or 0,
               "offset": a.get("offset") or 0}
        head = a.get("query") or a.get("album") or a.get("artist") or action
        self.fileToolStarted.emit("searching the library: " + str(head)[:60])

        def done(result):
            remaining["sink"][idx] = {"role": "tool", "tool_name": "music_library",
                                       "content": json.dumps(result)}
            n = result.get("count") if isinstance(result, dict) else None
            self.fileToolDone.emit(
                ("library: " + str(result.get("error")))[:200]
                if "error" in result else
                "library · %s %s" % ("" if n is None else n,
                                     "albums" if action == "albums" else "tracks"),
                "error" not in result)
            self._tool_done(remaining, calls)

        self._music_call(req, done)

    # ---- last.fm ------------------------------------------------------

    def _run_lastfm_tool(self, args, idx, remaining, calls):
        """One Last.fm call, on the network stack the rest of this window uses.

        `pylib/lastfm.py` owns the credentials and the signature; this owns the
        request, because a blocking urllib round trip on the GUI thread would
        freeze the window mid-reply. So the params and the api_sig come from
        there and the transport is QNetworkAccessManager, exactly like the
        Tavily path above."""
        a = args if isinstance(args, dict) else {}
        action = str(a.get("action") or "recent").strip().lower()
        spec = LASTFM_ACTIONS.get(action)
        if not spec:
            self._lastfm_fail(action, "unknown action: " + action, idx,
                              remaining, calls)
            return
        method, required, needs_auth = spec

        cfg = lastfmlib.load()
        if not lastfmlib.has_keys(cfg):
            self._lastfm_fail(action, "Last.fm is not set up: no API key. "
                              "Run apps/player/tools/lastfm-connect.py --keys "
                              "KEY SECRET (get one at " + lastfmlib.CREATE_PAGE
                              + ").", idx, remaining, calls)
            return
        if needs_auth and not lastfmlib.connected(cfg):
            self._lastfm_fail(action, "no Last.fm account is linked, so this "
                              "cannot be written. Run "
                              "apps/player/tools/lastfm-connect.py.",
                              idx, remaining, calls)
            return

        vals = {k: str(a.get(k) or "").strip()
                for k in ("artist", "track", "album", "tag", "user")}
        missing = [k for k in required if not vals.get(k)]
        if missing:
            self._lastfm_fail(action, "missing: " + ", ".join(missing),
                              idx, remaining, calls)
            return

        limit = max(1, min(int(a.get("limit") or 20), LASTFM_MAX_ROWS))
        params = {k: v for k, v in vals.items() if v}
        # `user` defaults to HIM. Every user.* method needs one and the linked
        # account is the only one he has ever meant by "my scrobbles".
        if method.startswith("user.") and not params.get("user"):
            params["user"] = lastfmlib.username(cfg)
            if not params["user"]:
                self._lastfm_fail(action, "no Last.fm account is linked, so "
                                  "there is no listening history to read. Run "
                                  "apps/player/tools/lastfm-connect.py.",
                                  idx, remaining, calls)
                return
        if not needs_auth:
            params["limit"] = limit
            if a.get("page"):
                params["page"] = max(1, int(a.get("page")))
        if method.startswith("user.getTop"):
            period = str(a.get("period") or "overall").strip()
            params["period"] = period if period in LASTFM_PERIODS else "overall"
        # A track/album/artist lookup answered against HIS account carries his
        # own playcount and loved flag, which is the fact worth having.
        if method in ("track.getInfo", "album.getInfo", "artist.getInfo"):
            me = lastfmlib.username(cfg)
            if me:
                params["username"] = me

        head = (vals.get("artist") or vals.get("tag") or vals.get("user")
                or params.get("user") or action)
        self.fileToolStarted.emit("last.fm: %s %s" % (action, str(head)[:50]))

        try:
            body = lastfmlib.request_params(method, params, signed=needs_auth,
                                            cfg=cfg)
        except lastfmlib.LastfmError as e:
            self._lastfm_fail(action, str(e), idx, remaining, calls)
            return

        # A write is a signed POST (Last.fm rejects a signed GET for the
        # write methods); a read is a plain GET of the same encoded params.
        url = QUrl(lastfmlib.API_ROOT if needs_auth
                   else lastfmlib.API_ROOT + "?" + body)
        req = QNetworkRequest(url)
        req.setRawHeader(b"User-Agent", lastfmlib.USER_AGENT.encode("utf-8"))
        if needs_auth:
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                          "application/x-www-form-urlencoded")
            reply = self._nam.post(req, body.encode("utf-8"))
        else:
            reply = self._nam.get(req)
        reply.finished.connect(
            lambda: self._on_lastfm(reply, action, limit, idx, remaining, calls))

    def _lastfm_fail(self, action, msg, idx, remaining, calls):
        remaining["sink"][idx] = {"role": "tool", "tool_name": "lastfm",
                                   "content": json.dumps({"error": msg})}
        self.fileToolDone.emit(("last.fm: " + msg)[:200], False)
        self._tool_done(remaining, calls)

    def _on_lastfm(self, reply, action, limit, idx, remaining, calls):
        if not self._busy:                 # turn was cancelled
            reply.deleteLater()
            return
        try:
            data = bytes(reply.readAll().data())
            obj = None
            try:
                obj = json.loads(data or b"{}")
            except ValueError:
                obj = None
            # A Last.fm refusal is a 4xx WITH a JSON body saying why, which is
            # worth far more to the model than "HTTP 403".
            if isinstance(obj, dict) and obj.get("error"):
                self._lastfm_fail(action, str(obj.get("message")
                                              or "Last.fm error"),
                                  idx, remaining, calls)
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._lastfm_fail(action, reply.errorString(), idx, remaining,
                                  calls)
                return
            if obj is None:
                self._lastfm_fail(action, "Last.fm returned something that is "
                                  "not JSON", idx, remaining, calls)
                return
            result = {"action": action,
                      "result": self._lastfm_project(obj, limit)}
            remaining["sink"][idx] = {"role": "tool", "tool_name": "lastfm",
                                       "content": json.dumps(result)}
            self.fileToolDone.emit("last.fm · " + action, True)
        finally:
            reply.deleteLater()
            self._tool_done(remaining, calls)

    @staticmethod
    def _lastfm_project(obj, limit):
        """Last.fm's response, trimmed to what is worth context.

        Generic rather than a shape per method on purpose: every response is
        one wrapper key around rows that carry five sizes of the same image,
        a streamable flag nobody wants and, on the info methods, a whole
        biography. Dropping those by NAME survives Last.fm adding a field;
        twenty hand-written projections would not."""
        def walk(o, depth=0):
            if isinstance(o, dict):
                return {k: walk(v, depth + 1) for k, v in o.items()
                        if k not in LASTFM_DROP}
            if isinstance(o, list):
                return [walk(v, depth + 1) for v in o[:limit]]
            if isinstance(o, str) and len(o) > LASTFM_STR_CHARS:
                return o[:LASTFM_STR_CHARS] + "…"
            return o

        out = walk(obj)
        # One wrapper key ("recenttracks", "topartists", …) around everything;
        # unwrap it so the model reads rows rather than a nesting level.
        if isinstance(out, dict) and len(out) == 1:
            out = next(iter(out.values()))
        text = json.dumps(out)
        if len(text) > LASTFM_CHARS:
            return {"truncated": True,
                    "note": ("cut at %d characters — ask for a smaller `limit`"
                             % LASTFM_CHARS),
                    "json": text[:LASTFM_CHARS]}
        return out

    def _player_put_on(self, action, args, idx, remaining, calls):
        """play_these / queue_these — the queue verbs, over player's own socket.

        Not MPRIS: `OpenUri` is a no-op in player's adapter and MPRIS has no
        append at all, while that socket already carries both (OPEN and QUEUE —
        apps/player/AGENTS.md, "The queue socket")."""
        paths = args.get("paths") if isinstance(args, dict) else None
        paths = ([str(p) for p in paths if str(p).strip()]
                 if isinstance(paths, list) else [])
        if not paths:
            self._player_result({"error": "%s needs `paths` — search the "
                                          "library first" % action},
                                idx, remaining, calls)
            return
        self.fileToolStarted.emit(
            ("playing " if action == "play_these" else "queueing ")
            + ("%d tracks" % len(paths) if len(paths) > 1
               else os.path.basename(paths[0])))

        def done(result):
            ok = isinstance(result, dict) and "error" not in result
            if ok:
                result = dict(result, did=action)
            self._player_result(result, idx, remaining, calls)
            self.fileToolDone.emit(
                "%s %d track%s" % ("playing" if action == "play_these" else "queued",
                                   len(paths), "" if len(paths) == 1 else "s")
                if ok else ("player: " + str(result.get("error")))[:200], ok)

        self._music_call({"op": "play" if action == "play_these" else "queue",
                          "paths": paths}, done)

    def _run_player_tool(self, args, idx, remaining, calls):
        """Drive the music player, and answer with what actually happened.

        Every action ends in a STATUS read, so the model reports the state it
        produced rather than the one it intended — and a failure is a REASON,
        never a silent no-op: nothing running on this machine's bus is the
        common one and a real answer (his library is on `top`, so a book window
        has nothing to drive)."""
        a = args if isinstance(args, dict) else {}
        action = str(a.get("action") or "status").strip().lower()
        target = str(a.get("player") or "").strip()
        if action in ("play_these", "queue_these"):
            self._player_put_on(action, a, idx, remaining, calls)
            return
        if action == "list":
            self._player_list(idx, remaining, calls)
            return

        def status(_rc=0, _out="", _err=""):
            self._pctl(["metadata", "--format", self.PLAYER_FORMAT],
                       lambda rc, out, err: self._player_answer(
                           action, rc, out, err, idx, remaining, calls),
                       target)

        # THE MIXER, not the player, is what "volume" and "mute" mean here —
        # unless he asked for that one app's own (`scope: player`).
        if action in ("volume", "mute") \
                and str(a.get("scope") or "system").lower() != "player":
            args_ = self._mixer_verb(action, a)
            if isinstance(args_, str):
                self._player_result({"error": args_}, idx, remaining, calls)
                return

            def mixed(ok):
                if not ok:
                    self._player_result(
                        {"error": "the system mixer refused %s (wpctl)" % action},
                        idx, remaining, calls)
                    return
                status()

            self._mixer_set(args_, mixed)
            return

        try:
            verb = self._player_verb(action, a)
        except ValueError as e:
            self._player_result({"error": str(e)}, idx, remaining, calls)
            return

        if not verb:
            status()
            return

        def after(rc, out, err):
            if rc != 0:
                self._player_result(
                    {"error": self._player_reason(err) or
                     ("%s failed" % action)}, idx, remaining, calls)
                return
            status()

        self._pctl(verb, after, target)

    @staticmethod
    def _mixer_verb(action, a):
        """The `wpctl` arguments for a system-wide volume change, or a reason
        it cannot be built."""
        if action == "mute":
            on = a.get("on")
            return ["set-mute", AUDIO_SINK,
                    "toggle" if on is None else ("1" if on else "0")]
        try:
            lvl = int(a.get("level"))
        except (TypeError, ValueError):
            return "volume needs `level`, 0-100"
        return ["set-volume", AUDIO_SINK, "%d%%" % max(0, min(100, lvl))]

    def _player_list(self, idx, remaining, calls):
        """Every player on the bus, so he (and the model) can name one."""
        def done(rc, out, err):
            names = [n.strip() for n in (out or "").splitlines() if n.strip()]
            if rc != 0 and not names:
                self._player_result(
                    {"ok": True, "players": [],
                     "note": self._player_reason(err)
                             or "nothing is on the MPRIS bus right now"},
                    idx, remaining, calls)
                return
            self._player_result({"ok": True, "players": names,
                                 "did": "list"}, idx, remaining, calls)

        self._pctl_raw(["-l"], done)

    def _pctl_raw(self, rest, cb):
        """playerctl with NO `-p` — for `-l`, which lists rather than drives."""
        proc = QProcess(self)
        self._procs.append(proc)

        def done():
            try:
                out = bytes(proc.readAllStandardOutput().data()).decode(
                    "utf-8", "replace")
                err = bytes(proc.readAllStandardError().data()).decode(
                    "utf-8", "replace")
                rc = proc.exitCode()
            except RuntimeError:
                return
            if proc in self._procs:
                self._procs.remove(proc)
            proc.deleteLater()
            cb(rc, out, err)

        proc.finished.connect(done)
        proc.errorOccurred.connect(
            lambda *_: cb(127, "", "playerctl is not installed here"))
        proc.start(PLAYERCTL, list(rest))

    @staticmethod
    def _player_verb(action, a):
        """The playerctl arguments for one action, or [] for a pure status.
        An action the player cannot really do is never offered (docs/DESIGN.md
        §10) — `Stop` and `OpenUri` are no-ops in its MPRIS adapter, so they are
        not in the tool's enum and land here as an unknown action."""
        if action == "status":
            return []
        if action in ("play", "pause", "next", "previous"):
            return [action]
        if action == "play_pause":
            return ["play-pause"]
        if action == "seek":
            try:
                secs = float(a.get("seconds", 0))
            except (TypeError, ValueError):
                raise ValueError("seek needs `seconds`")
            if a.get("relative"):
                # playerctl's own relative syntax: `10+` forward, `10-` back.
                return ["position", "%g%s" % (abs(secs), "-" if secs < 0 else "+")]
            return ["position", "%g" % max(0.0, secs)]
        if action == "volume":
            try:
                lvl = int(a.get("level"))
            except (TypeError, ValueError):
                raise ValueError("volume needs `level`, 0-100")
            return ["volume", "%.2f" % (max(0, min(100, lvl)) / 100.0)]
        if action == "shuffle":
            return ["shuffle", "on" if a.get("on", True) else "off"]
        if action == "loop":
            mode = str(a.get("mode") or "none").strip().lower()
            if mode not in ("none", "track", "playlist"):
                raise ValueError("loop `mode` is none, track or playlist")
            return ["loop", mode]
        raise ValueError("unknown action: " + action)

    @staticmethod
    def _player_reason(err):
        """playerctl's complaint, in one line — its "No players found" is the
        one the model must be able to relay honestly."""
        lines = [l.strip() for l in (err or "").splitlines() if l.strip()]
        if not lines:
            return ""
        why = lines[-1]
        if "no players found" in why.lower():
            return ("no music player is running on this machine — `player` "
                    "publishes MPRIS only while it is open, and his library "
                    "lives on top")
        return why

    def _player_answer(self, action, rc, out, err, idx, remaining, calls):
        if rc != 0 or not out.strip():
            self._player_result(
                {"error": self._player_reason(err)
                 or "no music player is running on this machine"},
                idx, remaining, calls)
            return
        result = self._player_parse(out.splitlines()[0])
        result["did"] = action
        # The volume he means is the machine's, always — so it is on every
        # answer, not only on a volume call.
        def with_mixer(vol):
            result.update(vol)
            self._player_result(result, idx, remaining, calls)

        self._mixer(with_mixer)

    def _player_result(self, result, idx, remaining, calls, name="control_media"):
        if idx is None:
            self.playerToolDone.emit(json.dumps(result))
            return
        self.playerToolDone.emit(json.dumps(result))
        remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                   "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    # ---- the video tool (show_video) ----

    def _show_video(self, url, alt, idx, remaining, calls):
        """Resolve ONE video to a playable stream URL and hand it to QML.

        Two routes, cheap one first: a URL that names a media file is PROBED,
        and if the server serves video bytes then that URL IS the stream — no
        subprocess and no resolver. Everything else — a YouTube watch page, a
        Vimeo link, a shortener, and a media-looking URL the server would not
        serve — goes to yt-dlp, which is the thing that knows how to turn a page
        into a stream.

        Nothing is downloaded on either route: the entry carries a `src` the QML
        MediaPlayer streams itself, so the picture appears at the speed of a
        manifest rather than of a file. `idx` is the tool call this answers, or
        None when nothing is waiting on a tool result (the harness)."""
        if not url or not re.match(r"^https?://", url, re.I):
            self.videoStarted.emit(url or "(no url)")
            self._video_failed(url, "not a valid http(s) video URL",
                               idx, remaining, calls)
            return
        self.videoStarted.emit(url)
        self._videos_shown.add(url)     # so `_attach_typed_videos` skips it
        if VIDEO_DIRECT_RE.search(url):
            self._video_probe(url, lambda ok, status, ctype:
                              self._on_video_direct(ok, ctype, url, alt,
                                                    idx, remaining, calls))
        else:
            self._video_resolve(url, alt, idx, remaining, calls, 0)

    def _video_probe(self, url, cb):
        """Ask the server for the FIRST KILOBYTE of a stream, and call back with
        (ok, status, content-type).

        A RANGED GET, not a HEAD — this is the check that decides whether a card
        is drawn at all, and on googlevideo the two answer differently: measured
        2026-08-23, the same URL gave 403 to a plain GET and 206 to a ranged one.
        A kilobyte is enough to see the status and the type and is the whole cost
        of knowing, before he clicks, that there is something on the other end."""
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                      "oracle-chatter/1.0")
        req.setRawHeader(b"Range", b"bytes=0-1024")
        reply = self._nam.get(req)

        def done():
            status = reply.attribute(
                QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            ctype = str(reply.header(
                QNetworkRequest.KnownHeaders.ContentTypeHeader)
                or "").split(";")[0].strip().lower()
            ok = (reply.error() == QNetworkReply.NetworkError.NoError
                  and (status is None or int(status) in (200, 206)))
            reply.deleteLater()
            cb(ok, int(status) if status is not None else 0, ctype)

        reply.finished.connect(done)

    def _on_video_direct(self, ok, ctype, url, alt, idx, remaining, calls):
        """A media-looking URL that really serves video is the stream itself.
        Anything else — a page wearing an .mp4 name, a refusal, a redirect to
        HTML — falls through to the resolver rather than handing QML a source
        that would fail silently in the decoder (docs/DESIGN.md §10)."""
        if not self._busy:            # turn was cancelled mid-probe
            return
        if ok and any(ctype.startswith(t) for t in VIDEO_CTYPES):
            name = os.path.basename(QUrl(url).path()) or url
            self._video_done({"ok": True, "url": url, "src": url, "alt": alt,
                              "title": name, "w": 0, "h": 0, "duration": 0,
                              "live": False}, idx, remaining, calls)
            return
        self._video_resolve(url, alt, idx, remaining, calls, 0)

    def _video_resolve(self, url, alt, idx, remaining, calls, step):
        """Run yt-dlp over one page, read the stream URL out of its JSON, and
        PROVE the stream answers before drawing a card for it.

        `step` walks VIDEO_RESOLVE_LADDER: each rung asks YouTube a different way,
        and a rung whose stream does not answer is not a failure, it is the next
        rung's turn. That ladder is the whole fix for the class of failure he hit
        on 2026-08-23 — see the constant.

        The async QProcess idiom the file tools use, so the window never blocks
        on a resolve; a resolver that hangs is killed at VIDEO_RESOLVE_MS."""
        proc = QProcess(self)
        self._procs.append(proc)
        state = {"done": False, "timeout": False}

        def nextrung(reason):
            if step + 1 < len(VIDEO_RESOLVE_LADDER):
                self._video_resolve(url, alt, idx, remaining, calls, step + 1)
            else:
                self._video_failed(url, reason, idx, remaining, calls)

        def settle(entry):
            if not entry.get("ok"):
                nextrung(entry.get("error", "could not resolve"))
                return

            def probed(ok, status, ctype):
                if not self._busy:
                    return
                if not ok:
                    nextrung("the site refused the stream it gave us"
                             + (" (HTTP %d)" % status if status else "")
                             + " — it may offer no playable single stream for "
                               "this video right now; try a different one")
                    return
                if entry.get("poster_url"):
                    self._video_poster(entry, idx, remaining, calls)
                else:
                    self._video_done(entry, idx, remaining, calls)

            self._video_probe(entry["src"], probed)

        def finished(*_):
            if state["done"]:
                return
            state["done"] = True
            if proc in self._procs:
                self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            if not self._busy:        # turn was cancelled mid-resolve
                return
            if state["timeout"]:
                settle({"ok": False, "error": "resolving that link timed out "
                        "after %d seconds" % (VIDEO_RESOLVE_MS // 1000)})
                return
            settle(self._video_entry(out, err, rc, url, alt))

        def failed(err):
            # FailedToStart is the only error that finished() will not follow,
            # and it means one thing worth saying: the resolver is not here.
            if state["done"] or err != QProcess.ProcessError.FailedToStart:
                return
            state["done"] = True
            if proc in self._procs:
                self._procs.remove(proc)
            proc.deleteLater()
            self._video_failed(url, "%s is not installed here, so only a DIRECT "
                               "video file URL can be shown — not a watch page"
                               % VIDEO_RESOLVER, idx, remaining, calls)

        def expire():
            if state["done"]:
                return
            state["timeout"] = True
            try:
                proc.kill()           # finished() then reports the timeout
            except RuntimeError:
                pass

        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        QTimer.singleShot(VIDEO_RESOLVE_MS, expire)
        proc.start(VIDEO_RESOLVER,
                   VIDEO_RESOLVE_BASE + VIDEO_RESOLVE_LADDER[step] + ["--", url])

    @staticmethod
    def _video_entry(out, err, rc, url, alt):
        """yt-dlp's JSON -> one entry. A resolve that produced no `url` failed,
        whatever the exit code says: with `-f b` the top-level `url` IS the
        chosen format's stream, and its absence means the only formats were a
        video/audio pair that would have to be downloaded and merged."""
        try:
            info = json.loads(out.decode("utf-8", "replace").strip() or "{}")
        except ValueError:
            info = {}
        if not isinstance(info, dict):
            info = {}
        src = str(info.get("url") or "")
        if not src:
            lines = [l.strip() for l in err.splitlines() if l.strip()]
            reason = lines[-1] if lines else (
                "no single playable stream at that link (exit %d)" % rc)
            reason = re.sub(r"^ERROR:\s*", "", reason)
            return {"ok": False, "error": reason}

        def num(key):
            try:
                return int(float(info.get(key) or 0))
            except (TypeError, ValueError):
                return 0

        return {"ok": True, "url": url, "src": src, "alt": alt,
                "title": str(info.get("title") or ""),
                "w": num("width"), "h": num("height"),
                "duration": num("duration"),
                "live": bool(info.get("is_live")),
                "poster_url": str(info.get("thumbnail") or "")}

    def _video_poster(self, entry, idx, remaining, calls):
        """Fetch the poster frame the resolver named, through the same save the
        images use. A card with no poster is a black box wearing a play marker,
        so this is worth one small GET — but it is never worth failing over: any
        problem here just means no poster, and the video still arrives."""
        url = entry.get("poster_url") or ""
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader,
                      "oracle-chatter/1.0")
        reply = self._nam.get(req)

        def done():
            if not self._busy:
                reply.deleteLater()
                return
            try:
                data = bytes(reply.readAll().data())
                ctype = str(reply.header(
                    QNetworkRequest.KnownHeaders.ContentTypeHeader)
                    or "").split(";")[0].strip().lower()
                if (reply.error() == QNetworkReply.NetworkError.NoError
                        and 0 < len(data) <= IMAGE_MAX_BYTES):
                    img = QImage()
                    if img.loadFromData(data) and not img.isNull():
                        path = self._save_image(data, url, ctype)
                        if path:
                            entry["poster"] = path
            except (ValueError, TypeError, OSError):
                pass
            reply.deleteLater()
            self._video_done(entry, idx, remaining, calls)

        reply.finished.connect(done)

    def _video_done(self, entry, idx, remaining, calls):
        """Hand the card to QML and the outcome to the model. The result says the
        video is SHOWN — like fetch_image's, and for the same reason: a note that
        asks the model to announce it buys a whole extra paragraph saying the
        video is above, which is a second message about a thing he can see."""
        entry.pop("poster_url", None)
        self.videoResult.emit(json.dumps(entry))
        if idx is None:
            return
        result = {"ok": True, "url": entry.get("url"),
                  "title": entry.get("title") or "",
                  "duration_seconds": entry.get("duration") or 0,
                  "note": ("The video is now playable inline in the chat, with "
                           "its title under it. He can see it, so do not "
                           "announce it or describe it unless he asks.")}
        remaining["sink"][idx] = {"role": "tool", "tool_name": "show_video",
                                   "content": json.dumps(result)}
        self._tool_done(remaining, calls)

    def _video_failed(self, url, reason, idx, remaining, calls):
        """Fail one video the same way for both audiences (docs/DESIGN.md §10):
        a crit line in the chat where the card would have been, and a tool error
        the model can act on."""
        self.videoResult.emit(json.dumps({"ok": False, "url": url,
                                          "error": reason}))
        if idx is None:
            return
        remaining["sink"][idx] = {"role": "tool", "tool_name": "show_video",
                                   "content": json.dumps({"error": reason,
                                                          "url": url})}
        self._tool_done(remaining, calls)

    # ---- the file tools (jailed, on top) ----

    @staticmethod
    def _fs_argv(target_host=None):
        """The command that runs one file op through tools/sandbox-fs.py.

        Mutating ops, and read ops with no explicit `target_host`, always land
        on `top` — unchanged from before, since the sandbox only ever lives
        there: local when this window IS top, over the ssh master
        tools/ollama-tunnel.sh already holds open (OLLAMA_SSH*) when it is
        book. A read-only op may instead ask for the OTHER machine via
        `target_host` ("top"/"book", his ask, 2026-08-11): if that is the
        machine this window already runs on it is once again a local call
        (SANDBOX_ROOT/READ_ROOT are the same paths on both — user `lam`,
        identical layout); otherwise it is a fresh ssh call to that host over
        the tailnet (both directions work — MagicDNS `top`/`book`; see
        AGENTS.md "Off-LAN: the tailnet"), reusing the tunnel's control master
        only for the one hop (book asking for top) that already has one open.
        The op JSON is written to stdin regardless of which branch runs."""
        host = target_host if target_host in ("top", "book") else "top"
        local = "book" if ON_BOOK else "top"
        if host == local:
            return [sys.executable, FS_SCRIPT, WRITE_ROOT, READ_ROOT]
        ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
        argv = [ssh, "-o", "BatchMode=yes"]
        if ON_BOOK and host == "top":
            ssh_host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
        else:
            ssh_host = host
        argv += [ssh_host, "python3", shlex.quote(FS_SCRIPT),
                 shlex.quote(WRITE_ROOT), shlex.quote(READ_ROOT)]
        return argv

    # ---- view_image: a LOCAL picture, for the model to look at ----

    def _view_image(self, args, idx, remaining, calls):
        """Read a local image through the jailed executor and attach it.

        Same executor, same wide READ root and same host branch as the read-only
        file tools — so `view_image` reaches exactly what `read_file` reaches and
        nothing more. The bytes never enter the tool RESULT (a base64 blob in the
        transcript would be unreadable and enormous): they are held in
        `_pending_vision` and go out as an ollama `images` block on a user
        message that `_tool_done` appends before the next post, which is how a
        dropped attachment reaches the model too.
        """
        path = str(args.get("path", "") or "").strip()
        target_host = str(args.get("host", "") or "").strip().lower() or None
        name = "view_image"

        def fail(reason):
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps({"error": reason})}
            self.fileToolDone.emit("view_image " + (path or "(no path)")
                                   + " — " + reason, False)
            self._tool_done(remaining, calls)

        if not path:
            self.fileToolStarted.emit("look at an image")
            fail("no path given")
            return
        # A model with no vision cannot be handed pixels; say so rather than
        # spending 8 MB of context on bytes it will ignore (§10).
        if "vision" not in (self._caps or []) or self._ctx_model != self._model:
            self.fileToolStarted.emit("look at " + os.path.basename(path))
            fail("this model has no vision support, so it cannot look at "
                 "images — tell him to pick a vision-capable model")
            return
        self.fileToolStarted.emit("look at " + os.path.basename(path))
        argv = self._fs_argv(target_host)
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            result = self._fs_result(out, err, rc)
            b64 = result.pop("b64", "") if isinstance(result, dict) else ""
            if "error" in result or not b64:
                fail(result.get("error", "could not read the image"))
                return
            self._pending_vision.append(b64)
            # Show him the same picture the model was handed. It is already on
            # disk, so the entry points straight at it — no copy, no re-encode.
            shown = os.path.abspath(os.path.expanduser(path))
            # Real pixel dimensions, so the view never upscales a small picture
            # to the column (ImageGallery sizes off w/h; 0 means "fill").
            probe = QImage()
            probe.loadFromData(base64.b64decode(b64))
            self.imageFetchStarted.emit(shown)
            self._emit_image({"ok": True, "url": "", "path": shown,
                              "alt": os.path.basename(shown),
                              "w": probe.width(), "h": probe.height()})
            remaining["sink"][idx] = {
                "role": "tool", "tool_name": name,
                "content": json.dumps(
                    {"ok": True, "path": result.get("path", path),
                     "media": result.get("media", ""),
                     "bytes": result.get("bytes", 0),
                     "note": ("The image is attached to your next turn — look at "
                              "it and answer from what you SEE. It is already "
                              "shown to him in the chat.")})}
            self.fileToolDone.emit("looked at " + os.path.basename(path), True)
            self._tool_done(remaining, calls)

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)
        proc.start(argv[0], argv[1:])
        proc.write(json.dumps({"op": "image", "path": path}).encode("utf-8"))
        proc.closeWriteChannel()

    def _show_image(self, args, idx, remaining, calls):
        """Put a local picture in the chat WITHOUT showing it to the model.

        The fast path is the honest one: a QML `Image` loads a local file, so if
        this window's own Qt can decode it, the entry points straight at it — no
        copy, no base64, no vision model, no context spent. Only when the file
        is not readable here (it is on the other machine) does it fall back to
        the same jailed executor `view_image` uses, saving the bytes locally so
        QML has something to load.
        """
        path = str(args.get("path", "") or "").strip()
        caption = str(args.get("caption", "") or "").strip()
        target_host = str(args.get("host", "") or "").strip().lower() or None
        name = "show_image"
        local_host = "book" if ON_BOOK else "top"

        def answer(result, ok=True):
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(
                ("showed " + os.path.basename(path)) if ok
                else ("show_image " + (path or "(no path)") + " — "
                      + str(result.get("error", ""))), ok)
            self._tool_done(remaining, calls)

        if not path:
            self.fileToolStarted.emit("show an image")
            answer({"error": "no path given"}, False)
            return
        self.fileToolStarted.emit("show " + os.path.basename(path))
        self._display_image(path, caption, target_host, answer)

    def _display_image(self, path, caption, target_host, answer, meta=""):
        """Draw one picture in the chat, wherever the file is.

        Local is the fast path and the honest one: a QML `Image` loads a local
        file, so if this window's Qt can decode it the entry points straight at
        it — no copy, no base64. A file on the OTHER machine comes back through
        the same jailed executor `view_image` uses and is saved locally, because
        QML cannot load a path that is not here. `answer(result, ok)` reports
        the outcome either way."""
        local_host = "book" if ON_BOOK else "top"
        here = os.path.abspath(os.path.expanduser(path))
        # ONE PICTURE, DRAWN ONCE. `_images_shown` keys on the URL, so it has
        # never covered a local file — and on 2026-08-24 a turn generated one
        # picture and then `show_image`d the same path twice, putting it in the
        # chat three times and telling him two had been generated. The file is
        # the identity here; a second request for one already on screen is
        # answered with where it is, not with another copy of it.
        if here in getattr(self, "_paths_shown", set()):
            answer({"ok": True, "path": here, "already_shown": True,
                    "note": ("This picture is ALREADY in the chat — you showed "
                             "it earlier this turn, so it was not drawn again. "
                             "There is one of it, not two. Do not call "
                             "show_image for it again, and do not tell him "
                             "more pictures were made than you made.")})
            return
        if target_host in (None, local_host):
            probe = QImage()
            if probe.load(here) and not probe.isNull():
                self._paths_shown.add(here)
                self.imageFetchStarted.emit(here)
                self._emit_image({"ok": True, "url": "", "path": here,
                                  "alt": caption or os.path.basename(here),
                                  "meta": meta,
                                  "w": probe.width(), "h": probe.height()})
                answer({"ok": True, "path": here, "width": probe.width(),
                        "height": probe.height(),
                        "note": ("Shown in the chat. You have NOT seen it — "
                                 "use view_image if you need to.")})
                return
            answer({"error": "not an image this window can display: " + path},
                   False)
            return

        # The OTHER machine: read it through the executor there and keep a local
        # copy, since QML can only load a local file.
        argv = self._fs_argv(target_host)
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            result = self._fs_result(out, err, rc)
            b64 = result.pop("b64", "") if isinstance(result, dict) else ""
            if "error" in result or not b64:
                answer({"error": result.get("error", "could not read the image")},
                       False)
                return
            try:
                data = base64.b64decode(b64)
            except (binascii.Error, ValueError):
                answer({"error": "the image did not decode"}, False)
                return
            probe = QImage()
            probe.loadFromData(data)
            saved = self._save_image(data, "file://" + here,
                                     result.get("media", ""))
            if not saved:
                answer({"error": "could not save the image locally"}, False)
                return
            self._paths_shown.add(here)
            self.imageFetchStarted.emit(saved)
            self._emit_image({"ok": True, "url": "", "path": saved,
                              "alt": caption or os.path.basename(here),
                              "meta": meta,
                              "w": probe.width(), "h": probe.height()})
            answer({"ok": True, "path": path, "width": probe.width(),
                    "height": probe.height(),
                    "note": "Shown in the chat. You have NOT seen it."})

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)
        proc.start(argv[0], argv[1:])
        proc.write(json.dumps({"op": "image", "path": path}).encode("utf-8"))
        proc.closeWriteChannel()

    # ---- generating a picture or a clip (make_image / make_video) ----

    #: Where input pictures land on `top` when the window is on book. They have
    #: to be ON the machine the backend runs on, and the two share no
    #: filesystem — only the ssh master — so they travel as a tar on the
    #: command's stdin rather than by path. /tmp because they are consumed by
    #: the one generation and nothing should keep them.
    PAINTER_IN_DIR = "/tmp/oracle-painter-in"
    #: …and how much may travel at once. A dropped screenshot is a megabyte; the
    #: cap is here so a video reference set cannot turn one tool call into a
    #: 200 MB ssh write.
    PAINTER_INPUT_MAX = 24 * 1024 * 1024

    @classmethod
    def _painter_inputs(cls, args, kind):
        """The input pictures this call feeds the generator, as (flag, path).

        Order and flag both matter: an edit's FIRST image is the subject and
        sets the output size, and a clip's two frames are two different ends of
        it, so they cannot be flattened into one list."""
        if kind == "video":
            pairs = [("--image", str(args.get("first_frame") or "").strip()),
                     ("--last-frame", str(args.get("last_frame") or "").strip())]
        else:
            raw = args.get("input_images")
            if isinstance(raw, str):
                raw = [raw]
            pairs = [("--image", str(p or "").strip())
                     for p in (raw if isinstance(raw, list) else [])]
        return [(f, os.path.abspath(os.path.expanduser(p))) for f, p in pairs if p]

    @classmethod
    def _painter_input_payload(cls, pairs):
        """Pack the input pictures for the machine the backend is on.

        Returns `(flags, stdin, error)`. On `top` there is nothing to pack — the
        paths are already where the generator will look. On book they are tarred
        and base64'd onto the command's stdin, under flat names, because the ssh
        master is the only thing the two machines share (the same reason
        painter uploads a drop over HTTP rather than passing a path)."""
        flags, seen, total = "", {}, 0
        for flag, path in pairs:
            if not os.path.isfile(path):
                return "", b"", "no such image: " + path
            try:
                total += os.path.getsize(path)
            except OSError as e:
                return "", b"", "cannot read %s: %s" % (path, e.strerror)
            if total > cls.PAINTER_INPUT_MAX:
                return "", b"", ("the input images come to more than %d MB"
                                 % (cls.PAINTER_INPUT_MAX // (1024 * 1024)))
            if not ON_BOOK:
                flags += " %s %s" % (flag, shlex.quote(path))
                continue
            name = seen.get(path)
            if name is None:
                name = "in%d%s" % (len(seen), os.path.splitext(path)[1] or ".png")
                seen[path] = name
            flags += " %s %s" % (flag, shlex.quote(cls.PAINTER_IN_DIR + "/" + name))
        if not ON_BOOK or not seen:
            return flags, b"", ""
        buf = io.BytesIO()
        try:
            with tarfile.open(fileobj=buf, mode="w") as tar:
                for path, name in seen.items():
                    tar.add(path, arcname=name)
        except (OSError, tarfile.TarError) as e:
            return "", b"", "could not pack the input images: %s" % e
        return flags, base64.b64encode(buf.getvalue()), ""

    @classmethod
    def _painter_argv(cls, args, kind="image"):
        """The one command that generates on `top`. `(argv, stdin, error)`.

        Four steps in one shell, because they are one act: put any input
        pictures where the backend can see them, start the backend if it is
        down (a user unit; `start` on a running one is a no-op), wait until it
        answers, then run painter's own headless generator. Same host branch as
        the code runner — local on top, over the tunnel's ssh master from book —
        because the weights and the GPU are only there. `$ORACLE_PAINTER`
        replaces the generator whole, which is how the harness drives a stub and
        never loads 20 GB of weights for a test."""
        def flag(name, key, cast=str):
            v = args.get(key)
            if v in (None, "", 0):
                return ""
            try:
                return " %s %s" % (name, shlex.quote(str(cast(v))))
            except (TypeError, ValueError):
                return ""

        pairs = cls._painter_inputs(args, kind)
        inputs, stdin, err = cls._painter_input_payload(pairs)
        if err:
            return [], b"", err
        edit = kind == "image" and bool(pairs)
        gen = os.environ.get("ORACLE_PAINTER", "").strip()
        cmd = gen or ("painter-qtenv python3 " + shlex.quote(PAINTER_SMOKE))
        stub = bool(gen)
        cmd += " --prompt " + shlex.quote(str(args.get("prompt") or ""))
        cmd += " --out-dir " + shlex.quote(MAKE_IMAGE_DIR)
        cmd += inputs
        # A MODE, not a model, when he named none: painter's own canonical pick
        # for the job (registry.MODES), so chatter and the button land on the
        # same file. An explicit model still wins, inside the generator.
        if not str(args.get("model") or "").strip():
            cmd += " --mode " + ("video" if kind == "video"
                                 else ("edit" if edit else "anime"))
        if edit:
            cmd += " --edit"
        cmd += flag("--negative", "negative")
        cmd += flag("--model", "model")
        cmd += flag("--aspect", "aspect")
        cmd += flag("--megapixels", "megapixels", float)
        cmd += flag("--batch", "count", int)
        cmd += flag("--width", "width", int)
        cmd += flag("--height", "height", int)
        cmd += flag("--steps", "steps", int)
        cmd += flag("--seed", "seed", int)
        if kind == "video":
            cmd += flag("--seconds", "seconds", float)
        cmd += " --timeout %d" % ((MAKE_VIDEO_MS if kind == "video"
                                   else MAKE_IMAGE_MS) // 1000 - 60)
        cmd += " --progress"
        # The BACKEND preamble is skipped for a stub: a test that starts
        # comfy-painter is a test that changed his machine, and this one did —
        # it left the daemon up and 1.1G held after a run [2026-08-23].
        wake = ("" if stub else
                "systemctl --user start comfy-painter.service >/dev/null 2>&1; "
                "for i in $(seq 1 90); do "
                "curl -sf -m 2 -o /dev/null http://127.0.0.1:8188/system_stats "
                "&& break; sleep 2; done; ")
        unpack = ("rm -rf %s; mkdir -p %s; base64 -d | tar -xf - -C %s; "
                  % (shlex.quote(cls.PAINTER_IN_DIR),
                     shlex.quote(cls.PAINTER_IN_DIR),
                     shlex.quote(cls.PAINTER_IN_DIR))) if stdin else ""
        # `exec`: the terminate() Stop sends must land on the GENERATOR, not on
        # a bash sitting in front of it — a shell that is only waiting dies and
        # leaves its child rendering (see `_stop_generating`).
        script = "mkdir -p %s; %s%sexec %s" % (shlex.quote(MAKE_IMAGE_DIR),
                                               unpack, wake, cmd)
        if ON_BOOK:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            return argv + [host, "bash -lc " + shlex.quote(script)], stdin, ""
        return ["bash", "-lc", script], stdin, ""

    def _booru_tags(self, args, idx, remaining, calls):
        """The tag vocabulary, searched or a draft checked (`pylib/boorutags`).

        Local, synchronous and small: it is a lookup in a 91k-row table, not a
        network call, and the answer is a handful of rows rather than a
        vocabulary dump."""
        a = args if isinstance(args, dict) else {}
        draft = str(a.get("check") or "").strip()
        query = str(a.get("query") or "").strip()
        self.fileToolStarted.emit("tags: " + (draft or query or "?")[:50])

        def answer(result, ok=True, line=""):
            remaining["sink"][idx] = {"role": "tool", "tool_name": "booru_tags",
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(line or ("booru_tags — "
                                            + str(result.get("error", ""))), ok)
            self._tool_done(remaining, calls)

        try:
            if draft:
                got = boorutags.check(draft)
                answer({"ok": True, **got,
                        "note": ("`unknown` tags are not on Danbooru and will "
                                 "do nothing — replace or drop them. `renamed` "
                                 "are real but written the wrong way; use the "
                                 "`tag` given. `suspect` is usually a CHARACTER "
                                 "or a series written out as a phrase instead "
                                 "of as its tag — search for it and use the "
                                 "real character tag plus its copyright tag, "
                                 "and let those carry the appearance instead "
                                 "of describing hair and eyes you are not "
                                 "sure of.")}, True,
                       "tags · %d ok, %d unknown" % (len(got["known"]),
                                                     len(got["unknown"])))
                return
            if not query:
                answer({"error": "booru_tags needs a query or a draft to check"},
                       False)
                return
            hits = boorutags.search(query, str(a.get("category") or ""),
                                    int(a.get("limit") or 25))
        except (ValueError, TypeError, OSError) as e:
            answer({"error": str(e)}, False)
            return
        answer({"ok": True, "query": query, "count": len(hits), "tags": hits,
                "note": ("Ordered by how many pictures carry the tag — the "
                         "first is the one the model saw most. Write them with "
                         "spaces, and an artist as @name.")
               if hits else "No tag on Danbooru matches that."},
               True, "tags · %d for %s" % (len(hits), query[:40]))

    def _make_image(self, args, idx, remaining, calls):
        self._make_media(args, idx, remaining, calls, "image")

    def _make_video(self, args, idx, remaining, calls):
        self._make_media(args, idx, remaining, calls, "video")

    def _make_media(self, args, idx, remaining, calls, kind):
        """Generate one picture or one clip through painter's backend and put it
        here. One body for both: the model family, the clock and how the result
        is DRAWN are the whole difference, and splitting them would be two
        copies of the warden dance.

        The warden goes FIRST (apps/pylib/warden.py): ollama is holding this
        model's weights and ComfyUI wants most of what is left, and the two
        colliding does not fail an allocation, it livelocks the desktop. A
        refusal is a reason the model relays, never a silent nothing."""
        a = args if isinstance(args, dict) else {}
        prompt = str(a.get("prompt") or "").strip()
        name = "make_video" if kind == "video" else "make_image"
        noun = "clip" if kind == "video" else "picture"

        def answer(result, ok=True, line=""):
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(line or (name + " — "
                                            + str(result.get("error", ""))), ok)
            self._tool_done(remaining, calls)

        if not prompt:
            self.fileToolStarted.emit("make a " + noun)
            answer({"error": name + " needs a prompt"}, False)
            return
        # ONE RENDER OF EACH KIND PER TURN [his, 2026-08-24: "it did generate a
        # video but then it tried to generate another until i stopped the comfy
        # server"]. The tool's own description and its result both say not to
        # call it again, and a model that has just watched twenty minutes of
        # silence does it anyway — so this is mechanical rather than worded. Per
        # KIND, not per turn: "make a picture and animate it" is one turn and two
        # calls, and that one is right. A second CLIP in the same turn is a
        # model deciding on its own to spend another twenty minutes of his GPU.
        if kind in self._made_this_turn:
            self.fileToolStarted.emit("make a " + noun)
            answer({"error": ("you already made a " + noun + " this turn, at "
                              + self._made_this_turn[kind] + ". He asked for "
                              "one. Do not generate another — talk about the "
                              "one you made, and wait for him to ask if he "
                              "wants it changed."),
                    "path": self._made_this_turn[kind]}, False,
                   name + ": one " + noun + " per turn")
            return
        if self._gen_procs:
            self.fileToolStarted.emit("make a " + noun)
            answer({"error": ("a generation is ALREADY RUNNING for this turn. "
                              "Wait for its result — do not call this again.")},
                   False, name + ": one at a time")
            return
        head = prompt if len(prompt) <= 60 else prompt[:59].rstrip() + "…"
        verb = ("animating" if (kind == "video" and a.get("first_frame"))
                else ("editing" if (kind == "image" and a.get("input_images"))
                      else "making"))
        self.fileToolStarted.emit("%s a %s: %s" % (verb, noun, head))

        def go(ok, reason):
            if not ok:
                # The lease is back on, so the rest of the turn is still
                # chatter's; it never got as far as freeing anything.
                self._warden.reserve("ollama", model=self._model)
                self.genFinished.emit(False)
                answer({"error": ("no room to generate right now — " +
                                  str(reason or "memory") + ". The " + noun +
                                  " cannot be made while this much of the "
                                  "machine is his model: tell him, and say a "
                                  "smaller model would leave room.")}, False,
                       name + ": no room — " + str(reason or ""))
                return
            self._make_media_run(a, answer, kind)

        # CHATTER GIVES ITS OWN WEIGHTS BACK FIRST. Its `send` lease is still
        # live — the turn is not over — and the warden never interrupts work in
        # flight, so with a 22 GiB model resident it would (correctly) refuse
        # every generation chatter itself asked for. But chatter is not a third
        # party here: it is between rounds, generating nothing, and its weights
        # are exactly the room the render needs. Dropping the lease lets the
        # warden see an idle ollama and free it, which is what he asked for —
        # unload to make room, reload to carry on — and `release()` takes the
        # lease back afterwards. [his, 2026-08-24]
        self._warden.done("ollama")
        # nbytes 0 — "a big family, size unknown", which is what the warden
        # reads it as; painter knows its weights, chatter does not. The lease is
        # SHORT and heartbeat-renewed rather than long and taken once, so a
        # chatter that dies mid-render costs painter two minutes, not an hour
        # (apps/pylib/warden.py: renew — which extends a lease and cannot free
        # or admit anything, unlike the re-reserve it replaces).
        self._warden.reserve("comfy", nbytes=0, cb=go, lease=WARDEN_LEASE_S)

    def _make_media_run(self, args, answer, kind):
        name = "make_video" if kind == "video" else "make_image"
        noun = "clip" if kind == "video" else "picture"
        limit_ms = MAKE_VIDEO_MS if kind == "video" else MAKE_IMAGE_MS
        argv, stdin, err = self._painter_argv(args, kind)
        if err:
            answer({"error": err}, False, name + ": " + err)
            return
        proc = QProcess(self)
        self._procs.append(proc)
        # STOP MEANS STOP THE RENDER TOO [his, 2026-08-24]. `cancel()` used to
        # abort the ollama stream and leave the backend sampling for another
        # twenty minutes with nobody waiting for it.
        self._gen_procs.append(proc)
        state = {"done": False, "timeout": False, "out": "", "meta": {}}

        # READ IT AS IT RUNS, not at the end. A render is minutes long, and the
        # generator prints `::progress FRAC LABEL` throughout (`--progress`) —
        # so the chat can draw a bar instead of one motionless line that reads
        # as stalled [his, 2026-08-24]. The whole of stdout is accumulated here
        # because `readAllStandardOutput` hands back only what has not been
        # read, and `finished` still needs the `saved …` lines.
        def drained():
            try:
                chunk = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            except RuntimeError:
                return
            if not chunk:
                return
            state["out"] += chunk
            for line in chunk.splitlines():
                line = line.strip()
                if line.startswith("::progress "):
                    bits = line[11:].split(" ", 1)
                    try:
                        frac = float(bits[0])
                    except (ValueError, IndexError):
                        continue
                    self.genProgress.emit(bits[1] if len(bits) > 1 else "", frac)
                elif line.startswith("::result "):
                    try:
                        got = json.loads(line[9:])
                    except ValueError:
                        continue
                    if isinstance(got, dict):
                        state["meta"] = got

        proc.readyReadStandardOutput.connect(drained)
        self.genProgress.emit("starting the backend", 0.0)
        # STILL WORKING. Waking the backend and loading 20 GB of weights can
        # outlast the reservation on its own, and a lapsed lease is the other
        # side taking the memory out from under a render (or worse, loading
        # beside it). The queue only becomes the busy signal once the graph is
        # submitted, which is the far end of exactly that window.
        beat = QTimer(self)
        beat.setInterval(WARDEN_BEAT_MS)
        beat.timeout.connect(lambda: self._warden.renew("comfy", WARDEN_LEASE_S))
        beat.start()

        def release():
            beat.stop()
            self._warden.done("comfy")
            # The turn is chatter's again: take the lease back so a render
            # started from painter cannot land on top of the model reloading
            # for the rest of this reply.
            self._warden.reserve("ollama", model=self._model)

        def finished(*_):
            if state["done"]:
                return
            state["done"] = True
            if proc in self._procs:
                self._procs.remove(proc)
            if proc in self._gen_procs:
                self._gen_procs.remove(proc)
            drained()
            try:
                err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
                rc = proc.exitCode()
            except RuntimeError:
                return
            out = state["out"]
            proc.deleteLater()
            release()
            self.genFinished.emit(not state["timeout"] and rc == 0)
            if state["timeout"]:
                answer({"error": "the generation ran past %d minutes and was "
                                 "stopped" % (limit_ms // 60000)}, False,
                       name + ": timed out")
                return
            made = re.findall(r"(?m)^\s*saved (.+?) \(\d+ bytes\)$", out)
            if kind == "video":
                clips = [m for m in made
                         if os.path.splitext(m)[1].lower() in VIDEO_SUFFIXES]
                made = clips or made
            if rc != 0 or not made:
                why = (([l for l in err.strip().splitlines() if l.strip()]
                        or [l for l in out.strip().splitlines() if l.strip()]
                        or ["the backend produced no " + noun])[-1])
                answer({"error": why[:400]}, False, name + ": " + why[:120])
                return
            path = made[-1]
            # THE CAPTION IS THE PROMPT THE GRAPH RAN, when the generator said
            # what that was: transformed to the family's spelling, and with the
            # negative folded in where NegPip took it. The tool's own argument
            # is what was ASKED for, which is not the same thing and hides the
            # half he cannot otherwise see [his, 2026-08-24].
            caption = (str((state["meta"] or {}).get("positive") or "").strip()
                       or str(args.get("prompt") or ""))
            meta = self._gen_meta(state["meta"])
            if kind == "video":
                self._display_clip(path, caption, args, answer, meta,
                                   state["meta"])
                return

            def shown(result, ok=True):
                if not ok:
                    answer(result, False)
                    return
                self._made_this_turn["image"] = path
                answer({"ok": True, "path": path,
                        **self._gen_facts(state["meta"]),
                        "note": ("Generated and placed in the chat. You have "
                                 "NOT seen it — view_image if you need to. Do "
                                 "not say where it is (above, below, inline) "
                                 "and do not describe it. It is made: do NOT "
                                 "call make_image again for this request. To "
                                 "remake the SAME picture, pass this seed "
                                 "back.")}, True,
                       "made " + os.path.basename(path))

            self._display_image(path, caption,
                                "top" if ON_BOOK else None, shown, meta)

        def failed(e):
            if state["done"] or e != QProcess.ProcessError.FailedToStart:
                return
            state["done"] = True
            if proc in self._procs:
                self._procs.remove(proc)
            if proc in self._gen_procs:
                self._gen_procs.remove(proc)
            proc.deleteLater()
            release()
            self.genFinished.emit(False)
            answer({"error": "could not start the image backend command"}, False)

        def expire():
            if state["done"]:
                return
            state["timeout"] = True
            try:
                proc.kill()
            except RuntimeError:
                pass

        proc.finished.connect(finished)
        proc.errorOccurred.connect(failed)
        QTimer.singleShot(limit_ms, expire)
        proc.start(argv[0], argv[1:])
        if stdin:
            proc.write(stdin)
        proc.closeWriteChannel()

    @staticmethod
    def _gen_facts(got):
        """WHAT THE GRAPH RAN, handed back to the MODEL as fields.

        The caption gives him the same facts; this gives them to the model,
        which otherwise cannot answer "lock that seed and change one thing" at
        all. On 2026-08-24 it spent five tool rounds — `file_metadata`,
        `find_files`, three `run_bash` — digging its own seed back out of the
        PNG it had just written, because the tool result had told it only that
        the picture existed."""
        if not isinstance(got, dict) or not got:
            return {}
        keep = ("seed", "model", "steps", "cfg", "sampler", "scheduler",
                "width", "height", "frames", "fps", "seconds", "positive",
                "negative")
        out = {k: got[k] for k in keep if got.get(k) not in (None, "")}
        # WHICH OF ITS TAGS DID NOTHING. A model that cannot see the picture has
        # no other way to learn that it invented half the prompt — it wrote
        # `lain igarashi` for a character named Iwakura and nothing said so
        # [his, 2026-08-24]. Only the misses are worth the tokens.
        tags = got.get("tags")
        if isinstance(tags, dict):
            bad = {k: tags[k] for k in ("unknown", "suspect", "renamed")
                   if tags.get(k)}
            if bad:
                out["tag_problems"] = bad
                out["tag_note"] = (
                    "These pieces of your prompt are NOT Danbooru tags, so they "
                    "did nothing in the picture: `unknown` is invented, "
                    "`suspect` is usually a character or series written as a "
                    "phrase instead of as its tag, and `renamed` was fixed for "
                    "you. Look them up with booru_tags before you prompt this "
                    "model again, and never spell a character's name from "
                    "memory.")
        return out

    @staticmethod
    def _gen_meta(got):
        """WHAT MADE IT, as one dim line under the caption [his, 2026-08-24].

        The picture's own caption is his prompt; this is the rest of the answer
        to "what is this" — the model, the size, the sampling and the seed,
        which is what he needs to make the same picture again. Read off the
        graph the generator actually ran (`::result`), not off the tool call, so
        everything that came from his painter settings and never appeared as an
        argument is in it too. Nothing to report is an empty line, not a row of
        `None`s."""
        if not isinstance(got, dict) or not got:
            return ""
        bits = []
        model = str(got.get("model") or "")
        if model:
            bits.append(re.sub(r"\.(safetensors|gguf|ckpt|pt)$", "", model))
        if got.get("seconds") and got.get("fps"):
            bits.append("%gs @ %g fps" % (got["seconds"], got["fps"]))
        if got.get("sized_by_image"):
            bits.append("sized by the input")
        elif got.get("width") and got.get("height"):
            bits.append("%dx%d" % (got["width"], got["height"]))
        if got.get("steps"):
            bits.append("%d steps" % int(got["steps"]))
        samp = "/".join(str(got[k]) for k in ("sampler", "scheduler")
                        if got.get(k) and str(got[k]).lower() != "none")
        if samp:
            bits.append(samp)
        if got.get("cfg") is not None:
            bits.append("cfg %g" % float(got["cfg"]))
        if got.get("seed") is not None:
            bits.append("seed %d" % int(got["seed"]))
        return " · ".join(bits)

    def _display_clip(self, path, caption, args, answer, meta="", got=None):
        """Put a generated clip in the chat, on its own poster frame.

        A VideoCard streams whatever `src` names, and a local file is a source
        QtMultimedia can open, so nothing is uploaded and nothing is resolved —
        the card points at the file the backend just wrote. The poster is one
        ffmpeg frame, because a card with no poster is a black box wearing a
        play marker (docs/DESIGN.md §10: the affordance should look like what it
        is). It is never worth failing over: no ffmpeg, no poster, same clip."""
        here = os.path.abspath(os.path.expanduser(path))
        poster = os.path.join(IMAGES_ROOT,
                              "clip-%s.png" % time.strftime("%Y%m%d-%H%M%S"))

        def emit(shot):
            probe = QImage()
            if shot and probe.load(shot) and not probe.isNull():
                w, h = probe.width(), probe.height()
            else:
                shot, w, h = "", 0, 0
            entry = {"ok": True, "url": "file://" + here,
                     "src": "file://" + here,
                     "path": here, "alt": caption, "meta": meta,
                     "title": os.path.basename(here),
                     "w": w, "h": h, "poster": shot,
                     "duration": float((got or {}).get("seconds")
                                       or args.get("seconds") or 0),
                     "live": False}
            self.videoResult.emit(json.dumps(entry))
            self._made_this_turn["video"] = here
            answer({"ok": True, "path": here, **Ollama._gen_facts(got),
                    "note": ("Generated and placed in the chat as a video he "
                             "can play. You have not seen it. Do not describe "
                             "it, do not say where it is, and do not offer to "
                             "make it again. To remake the same clip, pass "
                             "this seed back.")}, True,
                   "made " + os.path.basename(here))

        if ON_BOOK:
            # The clip is on top and QtMultimedia cannot stream a path that is
            # not here. Nothing to draw locally, so say where it is rather than
            # showing a card that would not play (docs/DESIGN.md §10).
            self._made_this_turn["video"] = here
            answer({"ok": True, "path": here, "host": "top",
                    "note": ("Generated on top, at this path. It is not on this "
                             "machine, so it is not playable in this window — "
                             "tell him where it is.")}, True,
                   "made " + os.path.basename(here))
            return
        try:
            os.makedirs(IMAGES_ROOT, exist_ok=True)
        except OSError:
            emit("")
            return
        shot = QProcess(self)
        self._procs.append(shot)

        def done(*_):
            if shot not in self._procs:
                return
            self._procs.remove(shot)
            try:
                rc = shot.exitCode()
            except RuntimeError:
                return
            shot.deleteLater()
            emit(poster if rc == 0 and os.path.exists(poster) else "")

        shot.finished.connect(done)
        shot.errorOccurred.connect(lambda *_: done())
        shot.start("ffmpeg", ["-y", "-loglevel", "error", "-i", here,
                              "-frames:v", "1", "-f", "image2", poster])

    # ---- the screen, as a picture (screenshot) ----

    def _screenshot(self, args, idx, remaining, calls):
        """Capture his screen, draw it in the chat, and hand it to the model.

        `grim` under Hyprland (wlroots) and Spectacle under Plasma (KWin, where
        grim cannot bind the protocol) — one capture, whichever the session is,
        chosen by what is actually there rather than by a guess about the
        session. The frame is drawn in the chat either way, because a model
        looking at his screen and him not seeing what it saw is exactly the
        secret docs/DESIGN.md §10 forbids.
        """
        name = "screenshot"
        show_only = bool(args.get("show_only"))
        vision = "vision" in (self._caps or []) and self._ctx_model == self._model

        def answer(result, ok=True, line=""):
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(line or ("screenshot — "
                                            + str(result.get("error", ""))), ok)
            self._tool_done(remaining, calls)

        self.fileToolStarted.emit("taking a screenshot")
        try:
            os.makedirs(IMAGES_ROOT, exist_ok=True)
        except OSError as e:
            answer({"error": str(e)}, False)
            return
        shot = os.path.join(IMAGES_ROOT,
                            "screen-%s.png" % time.strftime("%Y%m%d-%H%M%S"))
        argv = self._shot_argv(shot)
        if not argv:
            answer({"error": "no screenshot tool on this machine (grim under "
                             "Hyprland, spectacle under Plasma)"}, False)
            return
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            probe = QImage()
            if rc != 0 or not probe.load(shot) or probe.isNull():
                answer({"error": (err.strip().splitlines() or
                                  ["the capture produced no image"])[-1]}, False)
                return
            self.imageFetchStarted.emit(shot)
            self._emit_image({"ok": True, "url": "", "path": shot,
                              "alt": "his screen", "w": probe.width(),
                              "h": probe.height()})
            if show_only or not vision:
                note = ("Captured and shown in the chat. You have not seen it"
                        + ("." if show_only else
                           " — this model has no vision, so tell him to pick a "
                           "vision-capable one if he wants you to look."))
                answer({"ok": True, "path": shot, "width": probe.width(),
                        "height": probe.height(), "note": note}, True,
                       "screenshot · %dx%d" % (probe.width(), probe.height()))
                return
            try:
                raw = open(shot, "rb").read()
            except OSError as e:
                answer({"error": str(e)}, False)
                return
            if len(raw) > ATTACH_IMAGE_MAX:
                # Downscale rather than refuse: a 4K frame is megabytes of PNG
                # and the model reads it at a fraction of that anyway.
                small = probe.scaledToWidth(1600, Qt.TransformationMode.SmoothTransformation)
                buf = QBuffer()
                buf.open(QBuffer.OpenModeFlag.WriteOnly)
                small.save(buf, "PNG")
                raw = bytes(buf.data())
                buf.close()
            self._pending_vision.append(base64.b64encode(raw).decode("ascii"))
            answer({"ok": True, "path": shot, "width": probe.width(),
                    "height": probe.height(),
                    "note": ("The screen is attached to your next turn — look at "
                             "it and answer from what you SEE. He can see it "
                             "too, in the chat.")}, True,
                   "screenshot · %dx%d" % (probe.width(), probe.height()))

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)
        proc.start(argv[0], argv[1:])

    @staticmethod
    def _shot_argv(dest):
        """The capture command, by what is installed rather than by what session
        we think this is. `$ORACLE_SHOT_CMD` overrides it whole (the harness
        points it at a stub, so no test ever photographs his desk)."""
        override = os.environ.get("ORACLE_SHOT_CMD", "").strip()
        if override:
            return shlex.split(override) + [dest]
        for argv in ([shutil.which("grim"), dest],
                     [shutil.which("spectacle"), "-b", "-n", "-o", dest]):
            if argv[0]:
                return argv
        return []

    def _house_note(self, path):
        """The nearest house guide above `path`, named once per conversation.

        Walks up from the path to `$HOME` (never past it — `/` and `/nix/store`
        have no house rules and a stray hit there would be noise). Returns the
        sentence to hand back with the tool result, or "" when there is nothing
        to say or it has already been said this conversation.
        """
        p = str(path or "").strip()
        if not p:
            return ""
        try:
            here = Path(os.path.expanduser(p)).resolve()
        except (OSError, RuntimeError, ValueError):
            return ""
        home = Path.home().resolve()
        if not here.is_dir():
            here = here.parent
        found = None
        while True:
            for fn in HOUSE_FILES:
                cand = here / fn
                if cand.is_file():
                    found = cand
                    break
            if found is not None or here == home or here.parent == here:
                break
            here = here.parent
        if found is None:
            return ""
        key = str(found)
        if key in self._house_seen:
            return ""
        self._house_seen.add(key)
        return ("This tree has house rules: %s. It states how work is done "
                "here — what to run after a change, what never to edit by hand, "
                "how to commit. The NEAREST one to the file you are touching "
                "wins. Read the part that covers what you are about to do "
                "BEFORE you change anything in this tree." % key)

    def _run_fs_tool(self, name, args, idx, remaining, calls):
        """Run one file tool as an async QProcess, feeding the JSON result back
        into the tool loop exactly as the web search does. Concurrent with any
        other call in the round. `host`, on a read-only tool, is stripped from
        the args before they become the op request (sandbox-fs.py doesn't know
        about it) and instead selects which machine `_fs_argv` targets."""
        req = {k: v for k, v in args.items()} if isinstance(args, dict) else {}
        target_host = str(req.pop("host", "") or "").strip().lower() or None
        if name not in FILE_READ_TOOL_NAMES:
            target_host = None   # mutating tools have no host arg; ignore stray input
        req["op"] = FILE_OP[name]
        self.fileToolStarted.emit(self._fs_heading(name, args))
        argv = self._fs_argv(target_host)
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            result = self._fs_result(out, err, rc)
            # The tree's own guide, named the first time this conversation
            # touches that tree (HOUSE_FILES) — so he never has to point the
            # agent at the rules of the place it is standing in.
            if isinstance(result, dict) and "error" not in result:
                guide = self._house_note(
                    args.get("path") if isinstance(args, dict) else "")
                if guide:
                    result["guide"] = guide
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(self._fs_outcome(name, args, result),
                                   "error" not in result)
            self._tool_done(remaining, calls)

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)  # surfaced through finished
        proc.start(argv[0], argv[1:])
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()

    # ---- the code runner (jailed, on top) ----

    @staticmethod
    def _exec_argv():
        """The command that runs one Python program through tools/sandbox-exec.py
        against the sandbox on top — the same host branch as `_fs_argv`: local on
        `top`, over the tunnel's ssh master from `book`, so the code always runs
        where oracle's compute is. SANDBOX_ROOT is passed as the SCRATCH
        root — the runner's default working directory, not a jail — plus
        `--no-net` when ORACLE_EXEC_NET=0 asks for the old network cut."""
        extra = [] if EXEC_NET else ["--no-net"]
        if ON_BOOK:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            argv += [host, "python3", shlex.quote(EXEC_SCRIPT),
                     shlex.quote(SANDBOX_ROOT)] + extra
            return argv
        return [sys.executable, EXEC_SCRIPT, SANDBOX_ROOT] + extra

    def _run_exec_tool(self, name, args, idx, remaining, calls):
        """run_python / run_bash: execute a model-written program on the host and
        feed its stdout/stderr/exit code back into the tool loop, async and
        concurrent exactly like the file tools. tools/sandbox-exec.py is the one
        runner behind both — the tool name picks `lang`, and it caps time, CPU,
        memory and output; since 2026-08-22 it no longer cuts the network or
        confines the code (see WRITE_ROOT)."""
        a = args if isinstance(args, dict) else {}
        bash = name in BASH_TOOL_NAMES
        # bash takes `command`, python takes `code`; a model that mixes the two
        # up gets what it meant rather than an empty-program error.
        body = a.get("command") if bash else a.get("code")
        if not body:
            body = a.get("code") if bash else a.get("command")
        req = {"code": str(body or ""), "lang": "bash" if bash else "python",
               # Watch it work. An older executor over ssh ignores the key and
               # answers with one object exactly as before.
               "stream": True}
        if a.get("stdin") is not None:
            req["stdin"] = str(a.get("stdin"))
        if a.get("timeout") is not None:
            req["timeout"] = a.get("timeout")
        if a.get("cwd"):
            req["cwd"] = str(a.get("cwd"))
        self.fileToolStarted.emit("running bash" if bash else "running python")
        self.execStarted.emit("bash" if bash else "python")
        proc = QProcess(self)
        self._procs.append(proc)
        # The NDJSON stream arrives in whatever pieces the pipe gives us, so a
        # line can be split across two reads: hold the tail until it ends.
        buf = {"text": "", "last": ""}

        def pump():
            try:
                buf["text"] += bytes(proc.readAllStandardOutput()).decode(
                    "utf-8", "replace")
            except RuntimeError:
                return
            while "\n" in buf["text"]:
                line, buf["text"] = buf["text"].split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("t") in ("o", "e"):
                    self.execOutput.emit(str(obj.get("d") or ""))
                else:
                    buf["last"] = line      # the result object, always last

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            pump()
            try:
                err = bytes(proc.readAllStandardError())
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            out = (buf["last"] or buf["text"]).encode("utf-8")
            result = self._fs_result(out, err, rc)
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            self.execFinished.emit()
            self.fileToolDone.emit(self._exec_outcome(name, result),
                                   "error" not in result)
            self._tool_done(remaining, calls)

        proc.readyReadStandardOutput.connect(pump)
        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)  # surfaced through finished
        proc.start(self._exec_argv()[0], self._exec_argv()[1:])
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()

    @staticmethod
    def _exec_outcome(name, result):
        """The one-line disclosure for a run_python / run_bash call (the
        "files · N" block). Named by the language, so he can see which ran."""
        lang = "bash" if name in BASH_TOOL_NAMES else "python"
        if "error" in result:
            return (name + ": " + str(result["error"]))[:200]
        if result.get("timed_out"):
            return "%s timed out after %gs" % (lang, result.get("timeout", 0))
        rc = result.get("exit_code")
        return "%s exited %s" % (lang, rc if rc is not None else "?")

    @staticmethod
    def _fs_result(out, err, rc):
        """The store executor (file/session/memory) prints exactly one JSON
        object and exits 0; anything else — an ssh failure, a missing script, a
        crash — is a FAILURE the model and the user must see, never a silent
        empty result (docs/DESIGN.md §10).

        EMPTY stdout is such a failure and must not be read as an empty-but-ok
        `{}`: an `or "{}"` fallback there turned a broken store (e.g. ssh to a
        host whose checkout lacks the script) into a bogus success — `list`
        reported "0 memories" instead of the real error, and `refreshMemories`
        cached an empty set. Empty or unparseable stdout now falls through to
        the stderr-carrying error path."""
        text = out.decode("utf-8", "replace").strip()
        if text:
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                pass
        tail = (err.decode("utf-8", "replace").strip().splitlines() or [""])[-1]
        return {"error": "tool failed: " + (tail or ("exit %d" % rc))}

    @staticmethod
    def _fs_heading(name, args):
        a = args if isinstance(args, dict) else {}
        host = str(a.get("host") or "").strip().lower()
        suffix = " (book)" if name in FILE_READ_TOOL_NAMES and host == "book" else ""
        if name in ("find_files", "search_text"):
            verb = "finding" if name == "find_files" else "searching"
            return verb + " " + str(a.get("pattern") or "") + suffix
        p = str(a.get("path") or a.get("src") or ".")
        verb = {"list_dir": "listing", "read_file": "reading",
                "write_file": "writing", "edit_file": "editing",
                "move_path": "moving", "delete_path": "deleting",
                "make_dir": "creating", "show_tree": "tree of",
                "file_metadata": "inspecting"}.get(name, name)
        return verb + " " + p + suffix

    @staticmethod
    def _fs_outcome(name, args, result):
        a = args if isinstance(args, dict) else {}
        if "error" in result:
            p = str(a.get("path") or a.get("src") or "")
            return (name + ": " + str(result["error"]))[:200]
        if name == "list_dir":
            return "listed %s · %d entries" % (result.get("path", "."),
                                               result.get("count", 0))
        if name == "read_file":
            s, e, t = (result.get("start_line", 0), result.get("end_line", 0),
                       result.get("total_lines", 0))
            if result.get("binary"):
                return "read %s · binary, %d B" % (result.get("path", ""),
                                                   result.get("bytes", 0))
            return "read %s · lines %d–%d of %d" % (result.get("path", ""), s, e, t)
        if name == "write_file":
            return "%s %s · %d B" % ("created" if result.get("created") else "wrote",
                                     result.get("path", ""), result.get("bytes", 0))
        if name == "edit_file":
            n = result.get("replacements", 0)
            return "edited %s · %d replacement%s" % (result.get("path", ""), n,
                                                     "" if n == 1 else "s")
        if name == "move_path":
            return "moved %s → %s" % (result.get("src", ""), result.get("dst", ""))
        if name == "delete_path":
            return "deleted " + str(result.get("path", ""))
        if name == "make_dir":
            return "created " + str(result.get("path", "")) + "/"
        if name == "find_files":
            return "found %d match%s for %s" % (
                result.get("count", 0),
                "" if result.get("count", 0) == 1 else "es",
                str(a.get("pattern", "")))
        if name == "search_text":
            return "%d line%s in %d file%s for %s" % (
                result.get("match_count", 0),
                "" if result.get("match_count", 0) == 1 else "s",
                result.get("files_matched", 0),
                "" if result.get("files_matched", 0) == 1 else "s",
                str(a.get("pattern", "")))
        if name == "show_tree":
            return "tree of %s · %d entries" % (result.get("path", "."),
                                                result.get("count", 0))
        if name == "file_metadata":
            bits = [result.get("media_type") or result.get("kind") or "file"]
            if result.get("duration_seconds"):
                d = int(result["duration_seconds"])
                bits.append("%d:%02d" % (d // 60, d % 60))
            bits.append("%d B" % result.get("bytes", 0))
            return "%s · %s" % (result.get("name") or result.get("path", ""),
                                " · ".join(bits))
        return name + " ok"

    # ---- the session-read tools (past conversations, not the file jail) ----

    @staticmethod
    def _sessions_argv():
        """The command that runs one session-store op through
        tools/sessions-store.py, identical branch to Sessions._store_argv
        (duplicated rather than shared: Ollama and Sessions are independent
        QObjects with no reference to each other) — local on `top`, over the
        tunnel's ssh master from `book`."""
        if ON_BOOK:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            argv += [host, "python3", shlex.quote(SESSIONS_SCRIPT),
                     shlex.quote(SESSIONS_ROOT)]
            return argv
        return [sys.executable, SESSIONS_SCRIPT, SESSIONS_ROOT]

    def _run_session_tool(self, name, args, idx, remaining, calls):
        """list_sessions / read_session: the model reaching past THIS chat into
        his other oracle conversations, through the same store the session
        picker drives. Read-only from here — only `list`/`load` ops are ever
        sent, so a model call can never save or delete a session."""
        a = args if isinstance(args, dict) else {}
        if name == "list_sessions":
            req = {"op": "list"}
            heading = "listing sessions"
        else:
            sid = str(a.get("id", ""))
            req = {"op": "load", "id": sid}
            heading = "reading session " + sid
        self.fileToolStarted.emit(heading)
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            result = self._fs_result(out, err, rc)
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            self.fileToolDone.emit(self._session_outcome(name, a, result),
                                   "error" not in result)
            self._tool_done(remaining, calls)

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)  # surfaced through finished
        argv = self._sessions_argv()
        proc.start(argv[0], argv[1:])
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()

    @staticmethod
    def _session_outcome(name, args, result):
        if "error" in result:
            return (name + ": " + str(result["error"]))[:200]
        if name == "list_sessions":
            n = len(result.get("sessions", []))
            return "listed %d session%s" % (n, "" if n == 1 else "s")
        return "read session " + str(result.get("id", args.get("id", "")))

    # ---- oracle's own durable memories (create / read / update / delete) ----

    @staticmethod
    def _memories_argv():
        """The command that runs one memory-store op through
        tools/memory-store.py — the same host branch as `_sessions_argv`: local
        on `top`, over the tunnel's ssh master from `book`, so the memories live
        in one canonical place both machines share."""
        if ON_BOOK:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            argv += [host, "python3", shlex.quote(MEMORY_SCRIPT),
                     shlex.quote(MEMORY_ROOT)]
            return argv
        return [sys.executable, MEMORY_SCRIPT, MEMORY_ROOT]

    def _memory_store(self, req, on_done):
        """Run one memory-store op as an async QProcess (never blocks the UI),
        handing the parsed JSON reply to `on_done`. The shared idiom of the
        session/file stores: one JSON request on stdin, one JSON reply on stdout."""
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
                rc = proc.exitCode()
            except RuntimeError:
                return
            proc.deleteLater()
            on_done(self._fs_result(out, err, rc))

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)   # surfaced through finished
        argv = self._memories_argv()
        proc.start(argv[0], argv[1:])
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()

    @Slot()
    def refreshMemories(self):
        """Reload the memory cache the system prompt injects. Called at launch
        and again after a save/delete tool lands, so the next turn sees the
        current set."""
        def done(obj):
            if isinstance(obj, dict) and "error" not in obj:
                self._memories = obj.get("memories", []) or []
                self.memoriesChanged.emit()
        self._memory_store({"op": "list"}, done)

    @Property(int, notify=memoriesChanged)
    def memoryCount(self):
        """How many durable memories it is carrying — the standing fact behind
        `save_memory`, which otherwise only ever shows up inside a tool result
        [his, 2026-08-23]. Read off the same cache the system prompt injects, so
        the number and what the model actually knows are one thing."""
        return len(self._memories or [])

    def _run_memory_tool(self, name, args, idx, remaining, calls):
        """save_memory / list_memories / delete_memory: oracle managing its own
        durable memories. A save/delete refreshes the injected cache so the very
        next turn reflects the change, then the tool result is fed back like any
        other so the model knows it landed."""
        a = args if isinstance(args, dict) else {}
        if name == "list_memories":
            req = {"op": "list"}
            heading = "listing memories"
        elif name == "delete_memory":
            req = {"op": "delete", "id": str(a.get("id", ""))}
            heading = "forgetting " + str(a.get("id", ""))
        else:
            req = {"op": "save", "text": str(a.get("text", ""))}
            if a.get("id"):
                req["id"] = str(a.get("id"))
            heading = ("updating a memory" if a.get("id") else "saving a memory")
        self.fileToolStarted.emit(heading)

        def done(result):
            remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                       "content": json.dumps(result)}
            if name in ("save_memory", "delete_memory") and "error" not in result:
                self.refreshMemories()    # keep the injected cache current
            self.fileToolDone.emit(self._memory_outcome(name, a, result),
                                   "error" not in result)
            self._tool_done(remaining, calls)

        self._memory_store(req, done)

    @staticmethod
    def _memory_outcome(name, args, result):
        a = args if isinstance(args, dict) else {}
        if "error" in result:
            return (name + ": " + str(result["error"]))[:200]
        if name == "list_memories":
            n = len(result.get("memories", []))
            return "listed %d memor%s" % (n, "y" if n == 1 else "ies")
        if name == "delete_memory":
            return "forgot " + str(a.get("id", ""))
        mem = result.get("memory") or {}
        verb = "updated" if a.get("id") else "saved"
        return "%s memory %s" % (verb, mem.get("id", ""))

    # ---- self-authoring (make_tool / make_skill / make_agent) --------------

    def _run_author_tool(self, name, args, idx, remaining, calls):
        """The model writing its own tool, skill or subagent definition.

        Synchronous: it is a couple of local file writes, on the host the
        window runs on, exactly like `use_skill`'s read. Every failure is
        returned as an `error` the model can act on rather than raised — a
        refused name or a program that will not parse is something it can fix
        in the same turn."""
        a = args if isinstance(args, dict) else {}
        nm = str(a.get("name", "")).strip()
        drop = bool(a.get("delete"))
        kind = {"make_tool": "tool", "make_skill": "skill",
                "make_agent": "agent"}.get(name, "thing")
        self.fileToolStarted.emit(
            ("deleting %s %s" % (kind, nm or "?")) if drop
            else ("writing %s %s" % (kind, nm or "?")))
        if not AUTHOR_NAME_RE.fullmatch(nm):
            result = {"error": ("bad name %r: lowercase letters, digits, _ and "
                                "-, up to 64 characters" % nm)}
        elif name == "make_tool":
            result = self._author_tool(nm, a, drop)
        elif name == "make_skill":
            result = self._author_skill(nm, a, drop)
        else:
            result = self._author_agent(nm, a, drop)
        line = (("%s: %s" % (name, result["error"]))[:200] if "error" in result
                else "%s %s %s" % ("deleted" if drop else "wrote", kind, nm))
        remaining["sink"][idx] = {"role": "tool", "tool_name": name,
                                   "content": json.dumps(result)}
        self.fileToolDone.emit(line, "error" not in result)
        self._tool_done(remaining, calls)

    @staticmethod
    def _author_tool(nm, a, drop):
        """Write (or delete) one custom tool: the manifest and the program.

        The program is syntax-checked before it is installed — a tool that
        cannot parse is one the model would call, once, per turn, forever, and
        it costs nothing to find out here."""
        root = Path(CUSTOM_TOOLS_ROOT)
        manifest = root / (nm + ".json")
        if drop:
            gone = []
            for f in (manifest, root / (nm + ".py"), root / (nm + ".sh")):
                try:
                    f.unlink()
                    gone.append(str(f))
                except OSError:
                    pass
            if not gone:
                return {"error": "no tool named " + nm}
            return {"ok": True, "deleted": gone}
        if nm in BUILTIN_TOOL_NAMES:
            return {"error": ("%s is one of the app's own tools; pick another "
                              "name" % nm)}
        code = str(a.get("code") or "")
        if not code.strip():
            return {"error": "no code: the tool needs a program to run"}
        if len(code) > AUTHOR_MAX_CODE:
            return {"error": "code is too long (%d chars, max %d)"
                             % (len(code), AUTHOR_MAX_CODE)}
        lang = str(a.get("language") or "python").strip().lower()
        if lang not in ("python", "bash"):
            return {"error": "language must be python or bash"}
        params = a.get("parameters")
        if not isinstance(params, dict) or not params:
            params = {"type": "object", "properties": {}, "required": []}
        desc = str(a.get("description") or "").strip()
        if not desc:
            return {"error": ("no description: it is all a future model will "
                              "know about this tool")}
        try:
            secs = float(a.get("timeout") or CUSTOM_DEFAULT_SECS)
        except (TypeError, ValueError):
            secs = CUSTOM_DEFAULT_SECS
        secs = max(1.0, min(secs, CUSTOM_MAX_SECS))
        shebang = ("#!/usr/bin/env python3" if lang == "python"
                   else "#!/usr/bin/env bash")
        if not code.startswith("#!"):
            code = shebang + "\n" + code
        if not code.endswith("\n"):
            code += "\n"
        bad = Ollama._author_syntax(lang, code)
        if bad:
            return {"error": "the program does not parse: " + bad}
        prog = root / (nm + (".py" if lang == "python" else ".sh"))
        try:
            root.mkdir(parents=True, exist_ok=True)
            prog.write_text(code, encoding="utf-8")
            os.chmod(prog, 0o755)
            manifest.write_text(json.dumps(
                {"name": nm, "description": desc, "parameters": params,
                 "run": prog.name, "timeout": secs}, indent=2) + "\n",
                encoding="utf-8")
        except OSError as exc:
            return {"error": "could not write it: %s" % exc}
        live = nm in custom_tools()
        return {"ok": True, "name": nm, "manifest": str(manifest),
                "program": str(prog), "live": live,
                "note": ("It is loaded fresh every turn, so you can call it "
                         "from your next tool call." if live else
                         "Written, but it did not load — check the manifest.")}

    @staticmethod
    def _author_syntax(lang, code):
        """`None` if the program parses, else what the parser said."""
        if lang == "python":
            try:
                compile(code, "<tool>", "exec")
                return None
            except SyntaxError as exc:
                return "%s (line %s)" % (exc.msg, exc.lineno)
        import subprocess          # the only shell-out here; nothing else needs it
        try:
            out = subprocess.run(["bash", "-n"], input=code, text=True,
                                 capture_output=True, timeout=10)
            return None if out.returncode == 0 else (out.stderr.strip()[:400]
                                                     or "bash -n failed")
        except (OSError, subprocess.SubprocessError):
            return None          # no bash to check with: install it anyway

    @staticmethod
    def _author_skill(nm, a, drop):
        """Write (or delete) one skill: `<root>/<name>/SKILL.md`, frontmatter
        plus body — the same shape Claude Code reads, since it is the same
        directory."""
        d = Path(SKILLS_ROOT) / nm
        if drop:
            f = d / "SKILL.md"
            try:
                f.unlink()
            except OSError:
                return {"error": "no skill named " + nm}
            try:
                d.rmdir()                    # only if it is now empty
            except OSError:
                pass
            return {"ok": True, "deleted": str(f)}
        desc = str(a.get("description") or "").strip()
        body = str(a.get("instructions") or "").strip()
        if not desc:
            return {"error": ("no description: it is the line a future model "
                              "reads to decide whether this skill applies")}
        if not body:
            return {"error": "no instructions: the skill would load nothing"}
        if len(body) > SKILL_MAX_CHARS:
            return {"error": "instructions are too long (%d chars, max %d)"
                             % (len(body), SKILL_MAX_CHARS)}
        text = ("---\nname: %s\ndescription: %s\n---\n\n%s\n"
                % (nm, desc.replace("\n", " "), body))
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(text, encoding="utf-8")
        except OSError as exc:
            return {"error": "could not write it: %s" % exc}
        live = any(s["name"] == nm for s in skill_catalog())
        return {"ok": True, "name": nm, "path": str(d / "SKILL.md"),
                "live": live,
                "note": "use_skill can load it from your next tool call."}

    @staticmethod
    def _author_agent(nm, a, drop):
        """Write (or delete) one subagent definition: `<root>/<name>.md`,
        frontmatter plus the prompt. The resolved tool list comes back, so the
        model sees what its `tools:` string actually bought."""
        f = Path(AGENTS_ROOT) / (nm + ".md")
        if drop:
            try:
                f.unlink()
            except OSError:
                return {"error": "no agent definition named " + nm}
            builtin = any(b["name"] == nm for b in BUILTIN_AGENTS)
            return {"ok": True, "deleted": str(f),
                    "note": ("The app's own %s is back in its place." % nm
                             if builtin else "")}
        desc = str(a.get("description") or "").strip()
        prompt = str(a.get("prompt") or "").strip()
        if not desc:
            return {"error": ("no description: it is how a future model picks "
                              "this agent")}
        if not prompt:
            return {"error": "no prompt: the agent would be told nothing"}
        if len(prompt) > AGENT_MAX_CHARS:
            return {"error": "prompt is too long (%d chars, max %d)"
                             % (len(prompt), AGENT_MAX_CHARS)}
        tools = str(a.get("tools") or "").strip()
        model = str(a.get("model") or "").strip()
        head = ["---", "name: " + nm,
                "description: " + desc.replace("\n", " ")]
        if tools:
            head.append("tools: " + tools)
        if model:
            head.append("model: " + model)
        head.append("---")
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("\n".join(head) + "\n\n" + prompt + "\n",
                         encoding="utf-8")
        except OSError as exc:
            return {"error": "could not write it: %s" % exc}
        live = [x for x in agent_catalog() if x["name"] == nm]
        return {"ok": True, "name": nm, "path": str(f),
                "live": bool(live),
                "tools": _agent_tool_names(tools) if tools else "(the default set)",
                "note": "spawn_agent can use it from your next tool call."}

    # ---- skills (Claude Code's own, loaded on demand) ----

    def _run_skill_tool(self, args, idx, remaining, calls):
        """use_skill: hand the model one skill's instructions, or one of that
        skill's reference guides in full. Synchronous — a local file read, no
        subprocess and no host branch (the skills root exists on each machine
        chatter runs on). A
        whole guide comes back in ONE call rather than the model paging it
        through read_file, which is the point of it being a tool."""
        a = args if isinstance(args, dict) else {}
        name = str(a.get("name", "")).strip()
        guide = str(a.get("guide", "")).strip()
        catalog = skill_catalog()
        known = {s["name"] for s in catalog}
        self.fileToolStarted.emit(
            ("reading %s guide %s" % (name, guide)) if guide
            else ("loading skill " + (name or "?")))
        if name not in known:
            result = {"error": "unknown skill: " + (name or "(none given)"),
                      "available": sorted(known)}
            self._skill_done(result, "use_skill: " + result["error"], idx,
                             remaining, calls)
            return
        root = Path(SKILLS_ROOT) / name
        try:
            if guide:
                # The guide is resolved by BASENAME against the skill's own
                # references, never by the path the model hands us — the same
                # jail shape sessions-store.py uses for a session id.
                stem = Path(guide).name
                hit = next((f for f in self._skill_guides(root)
                            if f.name == stem or f.stem == Path(stem).stem), None)
                if hit is None:
                    result = {"error": "unknown guide: " + guide,
                              "skill": name,
                              "guides": [f.name for f in self._skill_guides(root)]}
                    self._skill_done(result, "use_skill: " + result["error"],
                                     idx, remaining, calls)
                    return
                text, cut = _skill_read(hit)
                result = {"skill": name, "guide": hit.name, "text": text}
                outcome = "read %s/%s" % (name, hit.name)
            else:
                text, cut = _skill_read(root / "SKILL.md")
                desc, body = _skill_front(text)
                guides = [f.name for f in self._skill_guides(root)]
                result = {"skill": name, "description": desc,
                          "instructions": body, "guides": guides}
                if guides:
                    result["note"] = ("Call use_skill again with guide=<name> "
                                      "to read one of these in full.")
                outcome = "loaded skill " + name
            if cut:
                result["truncated"] = ("output capped at %d characters"
                                       % SKILL_MAX_CHARS)
        except OSError as e:
            result = {"error": "cannot read skill %s: %s" % (name, e)}
            outcome = "use_skill: " + result["error"]
        self._skill_done(result, outcome, idx, remaining, calls)

    @staticmethod
    def _skill_guides(root):
        """A skill's reference guides — the markdown beside SKILL.md, whether
        it keeps them in `references/` or loose in the skill directory."""
        out = []
        for base in (root / "references", root):
            try:
                out += sorted(f for f in base.iterdir()
                              if f.is_file() and f.name != "SKILL.md"
                              and f.suffix.lower() in (".md", ".txt"))
            except OSError:
                pass
        return out

    def _skill_done(self, result, outcome, idx, remaining, calls):
        remaining["sink"][idx] = {"role": "tool", "tool_name": "use_skill",
                                   "content": json.dumps(result)}
        self.fileToolDone.emit(outcome[:200], "error" not in result)
        self._tool_done(remaining, calls)


class Backend(QObject):
    """The ollama server's lifecycle, drawn beside the model selector — the same
    backend controls painter gives ComfyUI (`apps/painter`: the systemd start/stop
    and comfy's `/free`), for a daemon oracle otherwise only talks to.

    Two things it exposes: UNLOAD the loaded model (ollama's analog of comfy's
    `/free` — a zero `keep_alive` on `/api/generate`, freeing the VRAM without
    stopping the daemon) and START/STOP the server. Ollama here is the SYSTEM
    `ollama.service` (`sys/ai/ollama.nix`), not a `--user` unit like
    comfy-painter, so start/stop go through `systemctl`, and a non-zero exit is
    reported as itself rather than as success (docs/DESIGN.md §10 — never report
    a change that did not happen).

    WHERE the systemctl runs is host-branched. On `top` the unit is local, so it
    is `sudo -A systemctl` (the NOPASSWD rule in `sys/ai/ollama.nix` means no
    prompt; the askpass dialog is only a fallback). On `book` there is no local
    `ollama.service` at all — the daemon runs on `top`, reached over the same ssh
    that `tools/ollama-tunnel.sh` forwards 11434 through — so start/stop is
    `ssh top sudo -n systemctl …`, non-interactive because top askpass cannot
    prompt over an ssh with no tty. That is why the NOPASSWD rule exists and why
    it is scoped to exactly `systemctl {start,stop} ollama.service`.

    Everything the controls light from is OBSERVED, not claimed (§10.6): `up`/
    `down` and the loaded model are polled from the daemon's own `/api/ps`,
    refreshed on a 3s timer and after every action, so the buttons follow what
    the server IS doing, not what the last click intended."""

    UNIT = "ollama.service"

    statusChanged = Signal()      # serverUp and/or the loaded-model list changed
    psSnapshot = Signal(str)      # the raw /api/ps body, for `Ollama.notePs`
    busyChanged = Signal()        # a start/stop is in flight
    note = Signal(str)            # a one-line result of an action, drawn as status

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._up = False
        self._loaded = []
        self._busy = False
        self._procs = []          # live QProcesses, so none is GC'd mid-run
        self._poll = QTimer(self)
        self._poll.setInterval(3000)
        self._poll.timeout.connect(self.pollStatus)
        self._poll.start()

    @Property(bool, notify=statusChanged)
    def serverUp(self):
        return self._up

    @Property("QStringList", notify=statusChanged)
    def loadedModels(self):
        return self._loaded

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    def _set_busy(self, v):
        if v != self._busy:
            self._busy = v
            self.busyChanged.emit()

    # ---- observed status: /api/ps tells us both reachability and what is loaded ----

    @Slot()
    def pollStatus(self):
        req = QNetworkRequest(QUrl(OLLAMA + "/api/ps"))
        reply = self._nam.get(req)
        reply.finished.connect(lambda: self._on_ps(reply))

    def _on_ps(self, reply):
        try:
            up = reply.error() == QNetworkReply.NetworkError.NoError
            loaded = []
            if up:
                raw = bytes(reply.readAll().data())
                try:
                    obj = json.loads(raw or b"{}")
                    loaded = sorted((m.get("name", "") for m in obj.get("models", [])
                                     if m.get("name")), key=str.lower)
                    # The same body carries the window each model is loaded in.
                    self.psSnapshot.emit(raw.decode("utf-8", "replace"))
                except (ValueError, TypeError):
                    up = False
            if up != self._up or loaded != self._loaded:
                self._up, self._loaded = up, loaded
                self.statusChanged.emit()
        finally:
            reply.deleteLater()

    # ---- unload the loaded model(s): comfy's /free, in ollama's dialect ----

    @Slot()
    def unloadModels(self):
        if not self._loaded:
            self.note.emit("no model is loaded")
            return
        pending = list(self._loaded)
        for name in pending:
            body = json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
            req = QNetworkRequest(QUrl(OLLAMA + "/api/generate"))
            req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                          "application/json")
            reply = self._nam.post(req, body)
            reply.finished.connect(lambda r=reply, n=name: self._on_unload(r, n))
        self.note.emit("unloading " + ", ".join(pending))

    def _on_unload(self, reply, name):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.note.emit("unload failed: " + reply.errorString())
            else:
                self.note.emit("unloaded " + name)
        finally:
            reply.deleteLater()
            self.pollStatus()

    # ---- start / stop the SYSTEM unit, through the askpass dialog ----

    def _systemctl(self, verb):
        # A HARNESS NEVER TOUCHES HIS DAEMON. The offscreen selftest pokes every
        # chrome id it can find, and Tools ▸ Stop Server is one of them —
        # measured 2026-08-23, a test run stopped the ollama he was using
        # (`sudo systemctl stop ollama.service` in the journal, from a poke).
        # The refusal is here rather than in the harnesses so a NEW harness
        # cannot reintroduce it (root AGENTS.md — a test that reaches the live
        # session is a bug in the test).
        if SELFTEST:
            self.note.emit("selftest: refusing to " + verb + " the server")
            return
        if ON_BOOK:
            # No local unit here; drive top's over the same ssh the tunnel uses.
            # `sudo -n` (no tty over ssh) relies on top's NOPASSWD rule for
            # exactly this command; ollama-tunnel.sh exports the resolved host
            # and the ssh control path so this reuses the tunnel's master.
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            argv += [host, "sudo", "-n", "systemctl", verb, self.UNIT]
            return argv
        return ["sudo", "-A", "systemctl", verb, self.UNIT]

    @Slot()
    def startServer(self):
        self._run(self._systemctl("start"), "starting the server",
                  "server started", "start failed")

    @Slot()
    def stopServer(self):
        self._run(self._systemctl("stop"), "stopping the server",
                  "server stopped", "stop failed")

    def _run(self, argv, reason, ok_msg, fail_label):
        self._set_busy(True)
        self.note.emit(reason + "…")
        proc = QProcess(self)
        self._procs.append(proc)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("SUDO_ASKPASS_REASON", reason)  # the dialog shows WHY (root AGENTS.md)
        proc.setProcessEnvironment(env)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = (bytes(proc.readAllStandardOutput()).decode(errors="replace")
                       + bytes(proc.readAllStandardError()).decode(errors="replace"))
                rc = proc.exitCode()
            except RuntimeError:
                return
            self._set_busy(False)
            # Report what happened, not what was asked (docs/DESIGN.md §10).
            if rc != 0:
                tail = out.strip().splitlines()
                self.note.emit(fail_label + ": " + (tail[-1] if tail else f"exit {rc}"))
            else:
                self.note.emit(ok_msg)
            self.pollStatus()
            proc.deleteLater()

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)   # reported through finished
        proc.start(argv[0], argv[1:])


class Sessions(QObject):
    """Named conversation sessions and their transcripts.

    Each session is one JSON transcript file in the canonical store
    (`SESSIONS_ROOT`), reached through `tools/sessions-store.py` — the same
    QProcess idiom the file tools use, so a save never blocks the UI and
    list/load results arrive on signals. oracle GENERATES the session id (a
    stable `sess-<ms>-<rand>` token, in QML), so the store only ever validates
    and writes; there is no id to mint and thus no round-trip before the first
    save. The list is `[{"id","title","updated","turns"}]`, newest first, for the
    session picker; `loaded` hands a whole transcript back as JSON for QML to
    rebuild the log from."""

    listChanged = Signal()
    loaded = Signal(str, str, str)     # id, title, turns as a JSON string
    saved = Signal(str, str)           # id, title — after a persist landed
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._list = []
        self._procs = []               # live QProcesses, so none is GC'd mid-run

    @Property("QVariantList", notify=listChanged)
    def sessions(self):
        return self._list

    @staticmethod
    def _store_argv():
        """The command that runs one store op through tools/sessions-store.py
        against the canonical store on top. On `top` it is local; on `book` it
        goes over the same ssh master tools/ollama-tunnel.sh holds open
        (OLLAMA_SSH*), so the sessions/transcripts live in one canonical place
        keyed to top and both machines share them. The op JSON is written to
        stdin."""
        if ON_BOOK:
            host = os.environ.get("OLLAMA_SSH_HOST", "top")
            ssh = os.environ.get("OLLAMA_SSH", "/usr/bin/ssh")
            argv = [ssh, "-o", "BatchMode=yes"]
            ctl = os.environ.get("OLLAMA_SSH_CTL")
            if ctl:
                argv += ["-o", "ControlMaster=auto", "-o", "ControlPersist=30",
                         "-o", "ControlPath=" + ctl]
            argv += [host, "python3", shlex.quote(SESSIONS_SCRIPT),
                     shlex.quote(SESSIONS_ROOT)]
            return argv
        return [sys.executable, SESSIONS_SCRIPT, SESSIONS_ROOT]

    def _run(self, req, on_done):
        proc = QProcess(self)
        self._procs.append(proc)

        def finished(*_):
            if proc not in self._procs:
                return
            self._procs.remove(proc)
            try:
                out = bytes(proc.readAllStandardOutput())
                err = bytes(proc.readAllStandardError())
            except RuntimeError:
                return
            proc.deleteLater()
            try:
                obj = json.loads(out.decode("utf-8", "replace") or "{}")
            except ValueError:
                tail = err.decode("utf-8", "replace").strip().splitlines()
                obj = {"error": "session store failed: "
                       + (tail[-1] if tail else "no output")}
            on_done(obj if isinstance(obj, dict) else {"error": "bad store reply"})

        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda *_: None)   # surfaced through finished
        argv = self._store_argv()
        proc.start(argv[0], argv[1:])
        proc.write(json.dumps(req).encode("utf-8"))
        proc.closeWriteChannel()

    @Slot()
    def refresh(self):
        def done(obj):
            if "error" in obj:
                self.error.emit(obj["error"])
                return
            self._list = obj.get("sessions", [])
            self.listChanged.emit()
        self._run({"op": "list"}, done)

    @Slot(str)
    def open(self, sid):
        def done(obj):
            if "error" in obj:
                self.error.emit(obj["error"])
                return
            self.loaded.emit(obj.get("id", ""), obj.get("title", ""),
                             json.dumps(obj.get("turns", [])))
        self._run({"op": "load", "id": sid}, done)

    @Slot(str, str, str)
    def save(self, sid, title, turns_json):
        try:
            turns = json.loads(turns_json or "[]")
        except ValueError:
            turns = []
        if not sid or not turns:
            return                      # nothing to persist yet
        def done(obj):
            if "error" in obj:
                self.error.emit(obj["error"])
                return
            self.saved.emit(obj.get("id", sid), obj.get("title", title))
            self.refresh()
        self._run({"op": "save", "id": sid, "title": title, "turns": turns}, done)

    @Slot(str)
    def remove(self, sid):
        def done(obj):
            if "error" in obj:
                self.error.emit(obj["error"])
                return
            self.refresh()
        self._run({"op": "delete", "id": sid}, done)


#: Now that `Ollama` exists, the collision set is what IT offers — never a
#: second list that could drift from it.
BUILTIN_TOOL_NAMES = {t["function"]["name"] for t in Ollama._builtin_tools()
                      if isinstance(t, dict) and t.get("function")}


def main():
    # OFFSCREEN ONLY (root AGENTS.md → "Testing without interfering with the
    # user"): the harness renders this window on the offscreen platform, never
    # on his screen, and refuses to run anywhere else.
    selftest = "--selftest" in sys.argv
    if selftest:
        sys.argv.remove("--selftest")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.pop("WAYLAND_DISPLAY", None)
        os.environ.pop("DISPLAY", None)

    # The Controls style, and with it the whole face: `Basic` in the Hyprland
    # session, `org.kde.desktop` under Plasma — which is not an imitation of the
    # KDE style but a renderer THROUGH it, so a Button here is drawn by Oxygen's
    # own code. pylib/kdeshell.py.
    kdeshell.pin_controls_style()

    # A QApplication under Plasma, the QGuiApplication we have always used
    # otherwise: QStyle is a QtWidgets class, and without it there is no system
    # style to paint with. See kdeshell.make_app.
    app = kdeshell.make_app(sys.argv, "oracle")
    if selftest and app.platformName() != "offscreen":
        raise SystemExit("selftest refuses to run on platform %r, not offscreen"
                         % app.platformName())
    app.setApplicationName("oracle")
    # The name he knows it by. `applicationName` stays `oracle` — the settings
    # key, the runtime paths and the source directory all do (AGENTS.md) — but
    # everything a person reads says chatter, About included.
    app.setApplicationDisplayName("chatter")
    app.setDesktopFileName("oracle")

    palette = Palette(theme_source(PANEL_THEME))
    style = DeskStyle()
    titlebar = Titlebar()
    ollama = Ollama()
    jobs = Jobs()
    ollama._jobs = jobs          # the tools and the tray read one Jobs
    backend = Backend()
    # One poll, two readers: the server controls light from /api/ps, and the
    # context stat reads the window each loaded model is really running in.
    backend.psSnapshot.connect(ollama.notePs)
    sessions = Sessions()
    clip = Clip()
    mdfmt = MdFormat()

    # TWO ROOFS, ONE APP (docs/DESIGN.md §7.6). Under Hyprland the QML tree IS
    # the window and the compositor draws the titlebar. Under Plasma the same
    # `Root.qml` is the central widget of a real QMainWindow, so the menubar,
    # the toolbar (with the model and session pickers on it) and the status bar
    # are KDE widgets and the window background is the system style's.
    plasma = is_plasma()
    shell = kdeshell.shell("chatter", size=(620, 720),
                           min_size=(420, 360)) if plasma else None
    engine = shell.engine() if plasma else QQmlApplicationEngine()
    if plasma:
        # THE SELECTOR IS HOW THE CONTENT CHANGES CLOTHES WITHOUT CHANGING CODE:
        # with "plasma" set, `qml/+plasma/Foo.qml` transparently replaces
        # `qml/Foo.qml` at every call site, so the compose box and the
        # attachment chips are QtQuick.Controls painted through the KDE style
        # while the Hyprland tree keeps ours, with no branch at either call site.
        kdeshell.select_plasma_files(engine)
    ctx = engine.rootContext()

    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("DeskStyle", style)
    ctx.setContextProperty("Titlebar", titlebar)
    ctx.setContextProperty("Ollama", ollama)
    ctx.setContextProperty("Jobs", jobs)
    ctx.setContextProperty("Backend", backend)
    ctx.setContextProperty("Sessions", sessions)
    ctx.setContextProperty("ollamaHost", OLLAMA)
    ctx.setContextProperty("Clip", clip)
    ctx.setContextProperty("Md", mdfmt)

    warnings = []
    engine.warnings.connect(
        lambda errs: warnings.extend(e.toString() for e in errs))

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(1)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    if plasma:
        # Root.qml, not Main.qml: the Window wrapper is the Hyprland roof, and
        # a QQuickWidget hosts an Item.
        if not shell.load(QML / "Root.qml"):
            print("failed to load Root.qml", file=sys.stderr)
            for w in shell.errors() + warnings:
                print(f"  {w}", file=sys.stderr)
            sys.exit(1)
        build_kde_chrome(shell, ollama, sessions, backend)
        shell.show()
    else:
        engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
        if not engine.rootObjects():
            for w in warnings:
                print(f"  {w}", file=sys.stderr)
            sys.exit(1)

    win = None if plasma else engine.rootObjects()[0]

    if selftest:
        sys.exit(run_selftest(app, shell, win, plasma, warnings))

    ollama.refreshModels()
    backend.pollStatus()
    sessions.refresh()
    ollama.refreshMemories()
    sys.exit(app.exec())


def run_selftest(app, shell, win, plasma, warnings):
    """Render this window offscreen and report what it is wearing.

    The only way to check the Plasma face without looking at it (docs/DESIGN.md,
    root AGENTS.md): `ORACLE_CHROME` prints the menubar, toolbar and status bar
    as text — a menu is not on screen until it is opened, so no render can show
    what is in one — `ORACLE_FACES` proves the file selector actually swapped
    the components, and `ORACLE_SHOT` writes the window to a PNG to LOOK at.

        QT_QPA_PLATFORMTHEME=kde DESK_SESSION=plasma ORACLE_CHROME=1 \
            ORACLE_SHOT=/tmp/chatter.png oracle-qtenv python3 main.py --selftest

    `QT_QPA_PLATFORMTHEME=kde` is not optional there: without it no KDE platform
    theme loads and the widgets take Qt's default light palette while the QML
    takes his dark scheme — a bug in the harness, not in the app.
    """
    rc = [0]

    def finish():
        # ORACLE_FAKE: a demo conversation in the log, so a render has bubbles
        # in it at all. It goes in through `loadTurns` — the function a session
        # switch already uses — so the harness invents no path of its own, and
        # nothing is written to the store (`saveCurrent` no-ops on an empty log).
        if os.environ.get("ORACLE_FAKE"):
            from PySide6.QtCore import (Q_ARG, Q_RETURN_ARG, QMetaObject,
                                        QObject)
            from PySide6.QtGui import QImage, QPainter
            # One generated picture, so a render shows where images sit in a
            # bubble (the top) with their caption. Written beside the selftest's
            # temp config, never into his image store.
            shot_img = os.path.join(IMAGES_ROOT, "demo-picture.png")
            try:
                os.makedirs(IMAGES_ROOT, exist_ok=True)
                pic = QImage(320, 180, QImage.Format.Format_RGB32)
                pic.fill(0x2f4858)
                pp = QPainter(pic)
                pp.setPen(0xffffff)
                pp.drawText(pic.rect(), 0x84, "demo picture")
                pp.end()
                pic.save(shot_img)
            except (OSError, RuntimeError):
                shot_img = ""
            # WHEN each demo turn happened: the first four yesterday, the rest
            # today, so a render shows the date divider a new day draws and the
            # old prompts are stale enough to be stamped into history.
            _now = int(time.time())
            _stamps = [_now - h * 3600 for h in (27, 27, 26, 26, 3, 3, 2, 2)]
            demo = [
                {"isUser": True, "who": "you", "body": "hi"},
                {"isUser": False, "who": "qwen3.6:35b-a3b",
                 "body": "Hello. Ask me anything."},
                {"isUser": True, "who": "you",
                 "body": "explain what a bubble layout is, briefly, and why it "
                         "reads better than a full-width row"},
                {"isUser": False, "who": "qwen3.6:35b-a3b",
                 "body": "A **bubble** hugs its own text and sits on the "
                         "speaker's side of the column, so the shape of the "
                         "conversation is legible before a word of it is read:\n\n"
                         "- short answers look short\n"
                         "- who said what needs no label\n\n"
                         "`code` and fenced blocks keep the monospaced face.",
                 "thinking": "The user wants a short answer. Keep it to a "
                             "definition plus two reasons.",
                 "thinkTokens": 24, "thinkMs": 12400},
                {"isUser": True, "who": "you", "body": "show me that picture"},
                {"isUser": False, "who": "qwen3.6:35b-a3b",
                 "body": "here it is — the caption is the model's own alt text.",
                 "images": json.dumps([{"ok": True, "url": "", "path": shot_img,
                                        "alt": "a demo picture, 320x180",
                                        "w": 320, "h": 180}]) if shot_img else "[]"},
                {"isUser": False, "who": "qwen3.6:35b-a3b",
                 "body": "server: connection refused", "isError": True},
                {"isUser": False, "who": "qwen3.6:35b-a3b",
                 "body": "and this one stopped mid-sen", "cutOff": True},
            ]
            for _i, _t in enumerate(demo):
                _t["ts"] = _stamps[_i]
            # Under Hyprland the QML root is the WINDOW; `loadTurns` lives on
            # the `Root` item inside it, and invoking it on the Window is a
            # silent no-op (the demo log simply never appears).
            target = shell.root if plasma else win.findChild(QObject, "content")
            QMetaObject.invokeMethod(target, "loadTurns",
                                     Q_ARG("QVariant", "demo"),
                                     Q_ARG("QVariant", "Demo conversation"),
                                     Q_ARG("QVariant", json.dumps(demo)))
            # Long enough for the async Image loads to land: three
            # processEvents grabbed the window before any picture had decoded,
            # so a demo image rendered as its caption and nothing else.
            _t0 = time.monotonic()
            while time.monotonic() - _t0 < 0.8:
                app.processEvents()
                time.sleep(0.01)
            # THE COMPOSE BUTTON'S THIRD STATE. The demo log ends on a finished
            # assistant turn, so the button beside the prompt box must be
            # offering `continue` [his, 2026-08-23] — and must go back to `send`
            # the moment there is something typed to send, since a prompt he has
            # written outranks carrying the last answer on. Both are printed
            # rather than rendered: a label is text, and reading it is the check
            # (tools/continue-button-test.py asserts on these two lines).
            target.setProperty("model", "demo:model")   # a model must be picked
            app.processEvents()
            _label = target.findChild(QObject, "sendLabel")
            _box = target.findChild(QObject, "promptBox")
            print("compose: canContinue=%s label=%r"
                  % (bool(target.property("canContinue")),
                     _label.property("text") if _label else None))
            print("compose face: %s" % (_box.property("face") if _box else None))
            if _box is not None:
                _box.setProperty("text", "a new question")
                app.processEvents()
                print("compose typed: canSend=%s label=%r"
                      % (bool(target.property("canSend")),
                         _label.property("text") if _label else None))
                _box.setProperty("text", "")
                app.processEvents()
            # THE TIMES, as text — tools/timestamp-test.py asserts on these
            # three lines. `ts` is what came back out of the store, `stamped` is
            # what an old turn looks like in the history the model gets, and
            # `newday` is which rows draw a date above them.
            if os.environ.get("ORACLE_TIMES"):
                _rows = json.loads(QMetaObject.invokeMethod(
                    target, "rowsJson", Q_RETURN_ARG("QVariant")) or "[]")
                print("times ts: %s" % json.dumps([r.get("ts") for r in _rows]))
                _stamped, _newday = [], []
                for _i, _t in enumerate(demo):
                    _stamped.append(QMetaObject.invokeMethod(
                        target, "stampedBody", Q_RETURN_ARG("QVariant"),
                        Q_ARG("QVariant", _t)))
                    _newday.append(bool(QMetaObject.invokeMethod(
                        target, "opensNewDay", Q_RETURN_ARG("QVariant"),
                        Q_ARG("QVariant", _i))))
                print("times stamped: %s" % json.dumps(_stamped))
                print("times newday: %s" % json.dumps(_newday))
        # ORACLE_SEND: drive real prompts through the window, against whatever
        # OLLAMA_HOST points at (tools/round-split-test.py points it at a stub
        # on 127.0.0.1 — never his daemon), then print the log as JSON. It is
        # the only way to check what the CHAT ROWS end up as, which is where the
        # per-round split lives.
        #
        # `;;` separates SEVERAL prompts, each sent once the last one has
        # finished — the only way to exercise anything that spans turns, which
        # is what the working memory across them is (tools/memory-carry-test.py).
        if os.environ.get("ORACLE_SEND"):
            from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QObject
            target = shell.root if plasma else win.findChild(QObject, "content")
            target.setProperty("model", os.environ.get("ORACLE_SEND_MODEL",
                                                       "stub:latest"))
            box = target.findChild(QObject, "promptBox")

            def _rows():
                return QMetaObject.invokeMethod(target, "rowsJson",
                                                Q_RETURN_ARG("QVariant"))

            for _prompt in os.environ["ORACLE_SEND"].split(";;"):
                box.setProperty("text", _prompt)
                app.processEvents()
                QMetaObject.invokeMethod(target, "send")
                _t0 = time.monotonic()
                while time.monotonic() - _t0 < 60:
                    app.processEvents()
                    time.sleep(0.01)
                    if time.monotonic() - _t0 < 1.0:
                        continue
                    try:
                        rows = json.loads(_rows() or "[]")
                    except ValueError:
                        continue
                    if rows and not any(r.get("streaming") for r in rows):
                        break
                for _ in range(20):
                    app.processEvents()
                    time.sleep(0.01)
            print("rows: %s" % _rows())
            # And what the turn meta block made of them (Root.turnJson).
            print("turns: %s" % QMetaObject.invokeMethod(target, "turnJson",
                                                         Q_RETURN_ARG("QVariant")))
        # ORACLE_MENU: open the log's right-click menu over the first reply,
        # which no other render can show — a menu is not on screen until it is
        # opened, and this one has no action, no id and no keyboard route. The
        # labels are printed (they differ per session: KDE's Copy vs ours) and
        # the window is left with the menu UP for the shot.
        if os.environ.get("ORACLE_MENU"):
            from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QObject
            target = shell.root if plasma else win.findChild(QObject, "content")
            # The VISUAL tree, not the QObject one: a Repeater's delegates
            # keep their QObject parent where it was, so `findChild` never
            # reaches a message (the same reason ORACLE_FACES walks childItems).
            def _named(it, want, depth=0):
                if it is None or depth > 16:
                    return None
                kids = (it.childItems() if hasattr(it, "childItems")
                        else it.children())
                for ch in kids:
                    if ch.objectName() == want:
                        return ch
                    hit = _named(ch, want, depth + 1)
                    if hit is not None:
                        return hit
                return None

            body = _named(target, "mdBody")
            menu = _named(target, "ctxMenu")
            if body is None or menu is None:
                print("menu: no mdBody/ctxMenu (needs ORACLE_FAKE)",
                      file=sys.stderr)
                rc[0] = 1
            else:
                rows = QMetaObject.invokeMethod(
                    target, "textMenu", Q_RETURN_ARG("QVariant"),
                    Q_ARG("QVariant", body), Q_ARG("QVariant", True))
                # A QML function returns a QJSValue, not a Python list: convert
                # it once here rather than at every use below.
                if hasattr(rows, "toVariant"):
                    rows = rows.toVariant()
                print("menu rows: %s"
                      % [r.get("label", "---") for r in (rows or [])])
                QMetaObject.invokeMethod(menu, "open", Q_ARG("QVariant", 40),
                                         Q_ARG("QVariant", 120),
                                         Q_ARG("QVariant", rows))
                _t0 = time.monotonic()
                while time.monotonic() - _t0 < 0.8:
                    app.processEvents()
                    time.sleep(0.01)
        # ORACLE_SELECT: put a real selection into the first reply, which is
        # what the &Edit menu's rows are enabled BY (win.noteSelection). No
        # other hook can produce one — a selection comes from a drag, and the
        # rows are deliberately dead without it, so without this the menu can
        # only ever be photographed disabled.
        if os.environ.get("ORACLE_SELECT"):
            from PySide6.QtCore import Q_ARG, QMetaObject, QObject
            target = shell.root if plasma else win.findChild(QObject, "content")

            def _sel_named(it, want, depth=0):
                if it is None or depth > 16:
                    return None
                kids = (it.childItems() if hasattr(it, "childItems")
                        else it.children())
                for ch in kids:
                    if ch.objectName() == want:
                        return ch
                    hit = _sel_named(ch, want, depth + 1)
                    if hit is not None:
                        return hit
                return None

            # The LONGEST reply, not the first: `_sel_named` stops at the
            # first match and with a demo conversation that is a one-word one,
            # where select(0,12) selects nothing and the check reads as broken.
            bodies = []

            def _sel_all(it, want, depth=0):
                if it is None or depth > 16:
                    return
                kids = (it.childItems() if hasattr(it, "childItems")
                        else it.children())
                for ch in kids:
                    if ch.objectName() == want:
                        bodies.append(ch)
                    _sel_all(ch, want, depth + 1)

            _sel_all(target, "mdBody")
            body = max(bodies, key=lambda b: len(str(b.property("text") or "")),
                       default=None)
            if body is None:
                print("select: no mdBody (needs ORACLE_FAKE)", file=sys.stderr)
                rc[0] = 1
            else:
                # int, not QVariant: TextEdit::select(int,int) is a real
                # slot signature and a QVariant arg silently matches nothing.
                QMetaObject.invokeMethod(body, "select", Q_ARG(int, 0),
                                         Q_ARG(int, 12))
                app.processEvents()
                root_item = shell.root if plasma else win.findChild(QObject, "content")
                print("select: body.selectedText=%r len(text)=%d"
                      % (body.property("selectedText"),
                         len(str(body.property("text") or ""))))
                print("select: selectedText=%r rows=%s"
                      % (root_item.property("selectedText"),
                         {i: (shell._actions[i].isEnabled() if plasma
                              and i in shell._actions else None)
                          for i in ("copy", "copy-message", "select-all")}))

        # ORACLE_POKE: fire the menu rows themselves, which is the only check
        # that the ids in `actions` and the ones `tbAction` answers are the same
        # set — a typo in either is silent (the row is there, the click does
        # nothing). Every one of them is state-free here: nothing is sent, no
        # session exists to delete, and the daemon is not touched.
        # A row whose id is NAMED instead — `ORACLE_POKE=edit-prompt,new-session`
        # — so a render can show what a menu row PUT ON SCREEN, which is the
        # only way to check a panel that has no other way in (the base-prompt
        # editor is reachable from a menu and nothing else).
        if os.environ.get("ORACLE_POKE"):
            _ids = os.environ["ORACLE_POKE"]
            for bid in (_ids.split(",") if _ids not in ("1", "") else
                        ("new-session", "prompt:concise", "detach",
                         "refresh-models")):
                if not plasma:
                    # Under Hyprland there are no QActions — the same ids go
                    # through the QML side's own `tbAction`, so a named poke
                    # renders that face of the same state.
                    from PySide6.QtCore import Q_ARG, QMetaObject, QObject
                    _root = win.findChild(QObject, "content")
                    QMetaObject.invokeMethod(_root, "tbAction",
                                             Q_ARG("QVariant", bid))
                    app.processEvents()
                    print(f"poke {bid}: ok")
                    continue
                act = shell._actions.get(bid)
                if act is None:
                    print(f"poke {bid}: NO ACTION", file=sys.stderr)
                    rc[0] = 1
                    continue
                act.trigger()
                app.processEvents()
                print(f"poke {bid}: ok")
            # A QQuickWidget's `grab()` returns its LAST RENDERED frame, and
            # `processEvents()` alone does not force a new one — a poke that
            # opened a panel photographed as if it had not (measured: byte-for-
            # byte the unpoked window). Let the render thread catch up.
            _t0 = time.monotonic()
            while time.monotonic() - _t0 < 0.8:
                app.processEvents()
                time.sleep(0.01)
            # ...and that the poke LANDED: the base-prompt radio set is the
            # one whose new state comes back through the table.
            if plasma:
                lit = [i for i, a in shell._actions.items()
                       if i.startswith("prompt:") and a.isChecked()]
                print("prompt set now = %r" % lit)
        # THE JOBS TRAY, as text — tools/jobs-test.py asserts on these lines,
        # in both faces. A row is only there when ORACLE_JOBS points at a
        # directory with jobs in it, which is how that harness feeds it without
        # starting a single process of his. It reads AFTER the render catch-up
        # above: a ListView has no delegates until something polishes it.
        from PySide6.QtCore import QMetaObject, QObject
        _root = shell.root if plasma else win.findChild(QObject, "content")
        _tray = _root.findChild(QObject, "jobsTray") if _root else None
        if _tray is not None:
            # The rows are ListView delegates: they exist one layout pass
            # after the model does, so a read without this counts zero.
            # A ListView builds its delegates on a polish pass, and
            # `processEvents()` alone does not get one — the same catch-up
            # the render below needs (measured: rows=0 without it).
            _t = time.monotonic()
            while time.monotonic() - _t < 0.4:
                app.processEvents()
                time.sleep(0.01)
            QMetaObject.invokeMethod(_tray, "layoutNow")
            app.processEvents()
            # VISUAL children, not QObject children: a ListView delegate keeps
            # its QObject parent where the delegate was defined, so
            # `findChildren` sees none of them (the tree dump below walks the
            # same way for the same reason).
            def _job_rows(it, depth=0):
                out = []
                if it is None or depth > 8:
                    return out
                kids = (it.childItems() if hasattr(it, "childItems")
                        else it.children())
                for ch in kids:
                    if ch.objectName() == "jobRow":
                        out.append(ch)
                    else:
                        out += _job_rows(ch, depth + 1)
                return out

            def _verbs(row, depth=0):
                """The verbs actually DRAWN on a row — the one that does not
                apply to its state is not there (docs/DESIGN.md §10.2)."""
                out = []
                if row is None or depth > 6:
                    return out
                kids = (row.childItems() if hasattr(row, "childItems")
                        else row.children())
                for ch in kids:
                    if ch.property("label") is not None \
                            and ch.property("face") is not None:
                        if bool(ch.property("visible")):
                            out.append(ch)
                    else:
                        out += _verbs(ch, depth + 1)
                return out

            _rows = _job_rows(_tray)
            print("jobs tray: face=%s visible=%s height=%d rows=%d"
                  % (_tray.property("face"), bool(_tray.property("visible")),
                     int(_tray.property("height") or 0), len(_rows)))
            for _r in _rows:
                _j = _r.property("job") or {}
                print("jobs row: face=%s state=%s label=%r verbs=%d"
                      % (_r.property("face"), _r.property("state_"),
                         _j.get("label"),
                         len(_verbs(_r))))
            print("jobs status right: %r" % _root.property("statusRight"))
        if plasma and os.environ.get("ORACLE_CHROME"):
            print(shell.dump_chrome())
        if os.environ.get("ORACLE_TREE"):
            # What the WIDGET half is wearing — the half a QML-only dump cannot
            # see, and the half that goes wrong when the KDE platform theme is
            # missing (kdeshell.apply_palette).
            from PySide6.QtGui import QIcon
            # `menubar=` is the trapdoor check: Show Menubar must be an action
            # of the WINDOW, not only a row inside the menubar it hides, or
            # Ctrl+M cannot bring it back (kdeshell._toggle_action).
            _mb = shell._actions.get("__show_menubar") if plasma else None
            print(f"style={app.style().objectName() if hasattr(app, 'style') else '-'} "
                  f"window={app.palette().window().color().name()} "
                  f"text={app.palette().windowText().color().name()} "
                  f"icons={QIcon.themeName()} "
                  f"menubar={'on-window' if _mb is not None and _mb in shell.window.actions() else 'menu-only'}")
            want = os.environ["ORACLE_TREE"]
            root_item = shell.root if plasma else win

            def walk(it, depth=0):
                if depth > 14 or it is None:
                    return
                # VISUAL children, not QObject children: a Repeater's delegates
                # keep their QObject parent where it was.
                kids = (it.childItems() if hasattr(it, "childItems")
                        else it.children())
                for ch in kids:
                    try:
                        cls = ch.metaObject().className()
                        if ch.property("height") is None:
                            walk(ch, depth)
                            continue
                        name = ch.property("label") or ch.property("text") or ""
                        if want == "1" or want.lower() in (cls + " " + str(name)).lower():
                            print("  " * depth + f"{cls} {str(name)[:24]!r} "
                                  f"x={ch.property('x')} w={ch.property('width')} "
                                  f"y={ch.property('y')} h={ch.property('height')} "
                                  f"vis={ch.property('visible')}")
                    except Exception:  # noqa: BLE001
                        pass
                    walk(ch, depth + 1)

            walk(root_item)
        if os.environ.get("ORACLE_FACES"):
            seen = {}

            def faces(it, depth=0):
                if depth > 14 or it is None:
                    return
                kids = (it.childItems() if hasattr(it, "childItems")
                        else it.children())
                for ch in kids:
                    f = ch.property("face")
                    # A STRING specifically: qmlcommon/VScroll.qml has a `color
                    # face` of its own and would otherwise report itself swapped
                    # in both sessions.
                    if isinstance(f, str) and f:
                        seen[ch.metaObject().className().split("_QMLTYPE")[0]] = str(f)
                    faces(ch, depth + 1)

            # Under Hyprland the root object is the Window; its children are
            # QObject children, which is enough to reach the tree from here.
            root_item = shell.root if plasma else win
            faces(root_item)
            for cls in sorted(seen):
                print(f"face {cls} = {seen[cls]}")
            if not seen:
                print("face: none found")
        shot = os.environ.get("ORACLE_SHOT")
        if shot:
            try:
                if plasma:
                    shell.window.grab().save(shot)
                else:
                    win.grabWindow().save(shot)
                print(f"selftest: wrote {shot}")
            except Exception as exc:  # noqa: BLE001
                print(f"selftest: shot failed: {exc}", file=sys.stderr)
        for w in warnings:
            print(f"QML WARNING: {w}", file=sys.stderr)
        if warnings:
            rc[0] = 1
        print(f"selftest: root loaded, {len(warnings)} QML warning(s)")
        app.quit()

    QTimer.singleShot(1200, finish)
    app.exec()
    return rc[0]


def build_kde_chrome(shell, ollama, sessions, backend):
    """chatter's Plasma chrome: the menubar and toolbar out of `actions`, the
    status bar out of `statusLine`/`statusRight`, and the two pickers that
    cannot be QActions — the model list and the session list — as real combo
    boxes on the toolbar, where Dolphin keeps its view controls."""
    from PySide6.QtCore import Q_ARG, QMetaObject
    from PySide6.QtWidgets import QComboBox, QMessageBox

    root = shell.root
    # No `titlebar` argument: chatter registers no hyprvtb buttons and its
    # bridge publishes no `buttonsChanged`, so `bind_chrome` binds the QML
    # root's own `actionsChanged` instead — `actions` is a binding over every
    # state it reports, so it fires whenever any of them moves.
    shell.bind_chrome(None)
    shell.bind_status()
    shell.bind_title("windowTitle")

    # The two pickers sit at the RIGHT end of the toolbar [his, 2026-08-22],
    # not beside the action buttons: an expanding blank widget in front of them
    # takes every pixel the buttons leave, which is how a QToolBar right-aligns
    # anything (it has no alignment of its own).
    from PySide6.QtWidgets import QWidget
    shell.toolbar_widget("main", QWidget(), stretch=True)

    # ---- the model picker -------------------------------------------------
    # A real QComboBox: the daemon's models, with the AGENT-SUGGESTED ones
    # ranked first and a separator ruling them off from the rest, exactly as the
    # QML dropdown does under Hyprland (`suggested.json` — apps/oracle/AGENTS.md).
    mirroring = []
    model_box = QComboBox()
    model_box.setMinimumWidth(220)
    model_box.setToolTip("the model this conversation talks to")

    def fill_models():
        mirroring.append(1)
        try:
            model_box.clear()
            names = list(ollama.models)
            for i, name in enumerate(names):
                model_box.addItem(name)
                if i + 1 == int(ollama.suggestedCount) and i + 1 < len(names):
                    model_box.insertSeparator(model_box.count())
            cur = str(root.property("model") or "")
            if cur:
                idx = model_box.findText(cur)
                if idx >= 0:
                    model_box.setCurrentIndex(idx)
            model_box.setEnabled(bool(names))
        finally:
            mirroring.pop()

    def picked_model(text):
        if mirroring or not text:
            return
        root.setProperty("model", text)

    def model_changed():
        if mirroring:
            return
        cur = str(root.property("model") or "")
        if cur and model_box.currentText() != cur:
            idx = model_box.findText(cur)
            if idx >= 0:
                mirroring.append(1)
                try:
                    model_box.setCurrentIndex(idx)
                finally:
                    mirroring.pop()

    model_box.textActivated.connect(picked_model)
    ollama.modelsChanged.connect(fill_models)
    msig = getattr(root, "modelChanged", None)
    if msig is not None and hasattr(msig, "connect"):
        msig.connect(model_changed)
    fill_models()
    shell.toolbar_widget("main", model_box)

    # ---- the session picker -----------------------------------------------
    # The same list the File menu carries, whole rather than capped, plus the
    # row that starts a new conversation — the one entry that is not a session.
    session_box = QComboBox()
    session_box.setMinimumWidth(200)
    session_box.setToolTip("the saved conversation on screen")

    def fill_sessions():
        mirroring.append(1)
        try:
            session_box.clear()
            session_box.addItem("New Session", "")
            for row in sessions.sessions:
                session_box.addItem(str(row.get("title") or "session"),
                                    str(row.get("id") or ""))
            sid = str(root.property("sessionId") or "")
            idx = session_box.findData(sid)
            session_box.setCurrentIndex(max(0, idx))
        finally:
            mirroring.pop()

    def picked_session(i):
        if mirroring or i < 0:
            return
        sid = str(session_box.itemData(i) or "")
        if not sid:
            QMetaObject.invokeMethod(root, "newSession")
        elif sid != str(root.property("sessionId") or ""):
            sessions.open(sid)

    def session_changed():
        if mirroring:
            return
        fill_sessions()

    session_box.activated.connect(picked_session)
    sessions.listChanged.connect(fill_sessions)
    ssig = getattr(root, "sessionIdChanged", None)
    if ssig is not None and hasattr(ssig, "connect"):
        ssig.connect(session_changed)
    tsig = getattr(root, "sessionTitleChanged", None)
    if tsig is not None and hasattr(tsig, "connect"):
        tsig.connect(session_changed)
    fill_sessions()
    shell.toolbar_widget("main", session_box)

    # ---- deleting a session is asked about first --------------------------
    # It is the one row here that destroys something of his, and the store keeps
    # no undo (docs/DESIGN.md §10.3). NOT `QMessageBox.question()`: the static
    # helpers run a nested exec() and hand the box to the KDE native dialog
    # helper, whose teardown segfaults the app (apps/AGENTS.md → kdeshell).
    boxes = []

    def confirm_delete():
        title = str(root.property("sessionTitle") or "this conversation")
        box = QMessageBox(shell.window)
        box.setOption(QMessageBox.Option.DontUseNativeDialog, True)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete session")
        box.setText("Delete “%s”?" % title)
        box.setInformativeText("The transcript is removed from the store. "
                               "This cannot be undone.")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)

        def answered(btn):
            if box.standardButton(btn) == QMessageBox.Yes:
                QMetaObject.invokeMethod(root, "deleteCurrentSession")
            box.hide()
        box.buttonClicked.connect(answered)
        boxes.append(box)          # a dialog owned by the stack crashes
        box.show()
        box.raise_()

    shell.on_action("delete-session", confirm_delete)
    # The action shortcuts are this face's (Ctrl+Return sends), and a bare-key
    # one would be typed into the compose box rather than fired — chatter has
    # none, so there is nothing here to guard.


if __name__ == "__main__":
    main()
