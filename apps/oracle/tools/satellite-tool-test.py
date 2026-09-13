#!/usr/bin/env python3
"""Real satellite tool loop against local HTTP fixtures; no external network."""
import base64
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("WAYLAND_DISPLAY", None); os.environ.pop("DISPLAY", None)
scratch = tempfile.TemporaryDirectory(prefix="chatter-satellite-")
os.environ["ORACLE_IMAGES"] = str(Path(scratch.name) / "images")
os.environ["ORACLE_API_KEYS"] = str(Path(scratch.name) / "keys.json")
Path(os.environ["ORACLE_API_KEYS"]).write_text(
    json.dumps({"firms": {"params": {"map_key": "secret-test-key"}}}))

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


class Stub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/geocode"):
            body, ctype = json.dumps([{"display_name": "Lisbon, Portugal",
                "category": "boundary", "type": "administrative",
                "boundingbox": ["38.691", "38.796", "-9.229", "-9.086"],
                "lat": "38.7223", "lon": "-9.1393"}]).encode(), "application/json"
        elif self.path.startswith("/gibs"):
            body, ctype = PNG, "image/png"
        elif self.path.startswith("/firms/"):
            assert "secret-test-key" in self.path
            body = (b"latitude,longitude,acq_date,acq_time,satellite,instrument,"
                    b"confidence,frp,daynight\n38.7,-9.1,2026-09-12,0830,N20,"
                    b"VIIRS,h,14.2,N\n")
            ctype = "text/csv"
        elif self.path.startswith("/goes"):
            body = b"<ListBucketResult><Contents><Key>ABI/test.nc</Key></Contents></ListBucketResult>"
            ctype = "application/xml"
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        assert self.path == "/stac"
        n = int(self.headers.get("Content-Length", 0)); json.loads(self.rfile.read(n))
        body = json.dumps({"features": [{"id": "S2-test", "properties": {
            "datetime": "2026-09-12T20:00:00Z", "eo:cloud_cover": 3},
            "assets": {"thumbnail": {"href": "https://example/preview.jpg"}}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *_): pass


srv = http.server.HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
os.environ.update({"ORACLE_GEOCODE": base + "/geocode",
                   "ORACLE_GIBS_WMS": base + "/gibs",
                   "ORACLE_CDSE_STAC": base + "/stac",
                   "ORACLE_FIRMS_AREA": base + "/firms",
                   "ORACLE_GOES_BUCKET": base + "/goes"})

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent.parent / "pylib")]
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
import main

app = QGuiApplication([]); o = main.Ollama(); o._busy = True
images = []; o.imageFetchResult.connect(lambda s: images.append(json.loads(s)))


def run(args):
    got = []
    rem = {"n": 1, "sink": [None], "done": lambda rows: got.extend(rows)}
    o._satellite_observe(args, 0, rem, [{}])
    timer = QTimer(); timer.timeout.connect(lambda: got and app.quit()); timer.start(10)
    stop = QTimer(); stop.setSingleShot(True); stop.timeout.connect(app.quit); stop.start(3000)
    app.exec(); timer.stop(); stop.stop()
    assert got, args
    return json.loads(got[0]["content"])


gibs = run({"source": "gibs", "place": "Lisbon", "date": "2026-09-12"})
assert gibs["ok"] and gibs["source"] == "NASA GIBS" and images[-1]["ok"]
assert Path(images[-1]["path"]).is_file()
assert images[-1]["satellite"] is True
assert images[-1]["meta"].startswith("NASA GIBS  ·  2026-09-12  ·  ")
assert "_image_meta" not in gibs
assert "_reject_blank" not in gibs
assert main.satellite.bbox_label([-10, 38, -8, 40]) == "10°W–8°W  38°N–40°N"
assert main.satellite.fit_dimensions([-87.6, 37.8, -84.8, 41.8]) == (413, 768)
assert main.satellite.GIBS_LAYERS["night"] == "VIIRS_CityLights_2012"
assert main.satellite.GIBS_LAYERS["night_daily"] == "VIIRS_NOAA20_DayNightBand"
blank = main.QImage(1024, 768, main.QImage.Format.Format_RGB32); blank.fill(0)
assert o._blank_satellite_image(blank) is True
blank.setPixelColor(0, 0, main.QColor("white"))
# One anomalous source pixel disappears in the downsample and remains empty.
assert o._blank_satellite_image(blank) is True
# The observed failure copied the downloaded GIBS PNG to /tmp and called
# show_image. Path-only deduplication treated that byte-identical copy as a
# second picture. It is now one image by content too.
copy = Path(scratch.name) / "copied-satellite.png"
shutil.copyfile(images[-1]["path"], copy)
before = len(images); got = []
rem = {"n": 1, "sink": [None], "done": lambda rows: got.extend(rows)}
o._show_image({"path": str(copy)}, 0, rem, [{}])
assert len(images) == before
assert json.loads(got[0]["content"])["already_shown"] is True
stac = run({"source": "copernicus", "bbox": [-10, 38, -8, 40]})
assert stac["rows"][0]["id"] == "S2-test"
fires = run({"source": "firms", "bbox": [-10, 38, -8, 40]})
assert fires["rows"][0]["satellite"] == "N20"
goes = run({"source": "goes", "bbox": [-10, 38, -8, 40]})
assert goes["rows"] == [{"object_key": "ABI/test.nc"}]
srv.shutdown()
print("satellite tool: ok")
