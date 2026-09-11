"""Plain-text album and artist descriptions from Last.fm and Bandcamp pages."""
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

import trackmatch


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("br", "p", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div"):
            self.parts.append("\n")

    def handle_data(self, text):
        if not self.hidden:
            self.parts.append(text)


class BandcampPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.album = {}

    def handle_starttag(self, tag, attrs):
        raw = dict(attrs).get("data-tralbum")
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    self.album = data
            except ValueError:
                pass


def bandcamp_description(page, album, url):
    parser = BandcampPage()
    parser.feed(page)
    current = parser.album.get("current") or {}
    if trackmatch.fold(str(current.get("title") or "")) != trackmatch.fold(str(album.get("title") or "")):
        return {}
    text_parser = PlainText()
    text_parser.feed(str(current.get("about") or ""))
    text = "".join(text_parser.parts).strip()
    # A shop URL is not an album write-up. Ignore link-only boilerplate.
    without_urls = re.sub(r"https?://\S+", "", text).strip()
    if len(without_urls.split()) < 8:
        return {}
    return {"description": text, "descriptionSource": "bandcamp",
            "descriptionUrl": url}


def _lastfm_wiki(remote):
    """The wiki body and its Last.fm page, or an empty result."""
    wiki = remote.get("wiki") or remote.get("bio") or {}
    if not isinstance(wiki, dict):
        return {}
    raw = wiki.get("content") or wiki.get("summary") or ""
    parser = PlainText()
    parser.feed(str(raw))
    text = "".join(parser.parts)
    # Last.fm appends a link and licensing footer to otherwise empty wikis.
    text = re.split(r"\s*Read more on Last\.fm", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    url = str(remote.get("url") or "")
    parsed = urlsplit(url)
    if not text or parsed.scheme not in ("http", "https") or parsed.hostname not in ("last.fm", "www.last.fm"):
        return {}
    return {"description": text, "descriptionSource": "last.fm",
            "descriptionUrl": url}


def lastfm_description(answer, album):
    """Do not turn a same-title album or an artist biography into album prose."""
    remote = (answer or {}).get("album") or {}
    if not isinstance(remote, dict):
        return {}
    for local_key, remote_key in (("title", "name"), ("artist", "artist")):
        wanted = trackmatch.fold(str(album.get(local_key) or ""))
        if not wanted or wanted != trackmatch.fold(str(remote.get(remote_key) or "")):
            return {}
    return _lastfm_wiki(remote)


def lastfm_artist_description(answer, name):
    """A biography only for the artist that was asked for. Last.fm answers a
    near miss with its own best guess, and the wrong life story reads exactly
    like a right one."""
    remote = (answer or {}).get("artist") or {}
    if not isinstance(remote, dict):
        return {}
    wanted = trackmatch.fold(str(name or ""))
    if not wanted or wanted != trackmatch.fold(str(remote.get("name") or "")):
        return {}
    return _lastfm_wiki(remote)
