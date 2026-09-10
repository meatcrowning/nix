#!/usr/bin/env python3
"""Pure fixture checks for album write-up identity, markup and boilerplate."""
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent / "pylib")]
from albumprose import lastfm_description, bandcamp_description

album = {"title": "Hit Vibes", "artist": "SAINT PEPSI"}
remote = {"name": "HIT VIBES", "artist": "Saint Pepsi",
          "url": "https://www.last.fm/music/Saint+Pepsi/HIT+VIBES",
          "wiki": {"content": '<p>A &amp; B.</p><script>hidden</script><p>Second paragraph.</p> '
                   '<a href="https://www.last.fm/music/example">Read more on Last.fm</a>. '
                   'User-contributed text is available under a license.'}}
result = lastfm_description({"album": remote}, album)
assert result["description"] == "A & B.\n\nSecond paragraph."
assert result["descriptionSource"] == "last.fm"
assert not lastfm_description({"album": {**remote, "artist": "Someone Else"}}, album)
assert not lastfm_description({"album": {**remote, "name": "Other Album"}}, album)
assert not lastfm_description({"album": {**remote, "url": "https://last.fm.evil.test/"}}, album)
assert not lastfm_description({"album": {**remote, "wiki": {"summary": "Read more on Last.fm"}}}, album)
assert not lastfm_description({"album": {**remote, "wiki": {}}}, album)

def page(title, about):
    data = {"current": {"title": title, "about": about}}
    return '<script data-tralbum="' + html.escape(json.dumps(data), quote=True) + '"></script>'

url = "https://example.bandcamp.com/album/hit-vibes"
text = "An album description with enough actual words to explain the release."
assert bandcamp_description(page("Hit Vibes", text), album, url)["description"] == text
assert not bandcamp_description(page("Other Album", text), album, url)
assert not bandcamp_description(page("Hit Vibes", "https://shop.example.com/"), album, url)
assert not bandcamp_description("<html>unavailable</html>", album, url)
print("album prose: ok")
