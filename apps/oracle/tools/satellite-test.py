#!/usr/bin/env python3
"""Chatter's satellite requests are bounded, dated and parseable; no network."""
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import satellite


box = satellite.bounds({"latitude": 38.7223, "longitude": -9.1393,
                        "radius_km": 50})
assert len(box) == 4 and box[0] < -9.1393 < box[2]
assert box[1] < 38.7223 < box[3]

url, layer = satellite.gibs_url(box, "natural", "2026-09-12", 9000, 20)
q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
assert layer == "MODIS_Terra_CorrectedReflectance_TrueColor"
assert q["time"] == ["2026-09-12"] and q["srs"] == ["EPSG:4326"]
assert q["width"] == ["1600"] and q["height"] == ["256"]

body = satellite.stac_body(box, "optical", "2026-09-12", 14, 12, 5)
assert body["collections"] == ["sentinel-2-l2a"]
assert body["query"]["eo:cloud_cover"]["lte"] == 12
assert body["datetime"].endswith("2026-09-12T23:59:59Z")

stac = satellite.stac_result({"features": [{
    "id": "S2-test", "properties": {"datetime": "2026-09-12T20:00:00Z",
    "eo:cloud_cover": 4.2, "platform": "sentinel-2b"},
    "assets": {"thumbnail": {"href": "https://example/preview.jpg"}}}]})
assert stac == [{"id": "S2-test", "acquired": "2026-09-12T20:00:00Z",
                 "cloud_cover": 4.2, "platform": "sentinel-2b",
                 "preview": "https://example/preview.jpg"}]

fires = satellite.firms_result(
    "latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp,daynight\n"
    "38.7,-9.1,2026-09-12,0830,N20,VIIRS,h,14.2,N\n", 10)
assert fires[0]["acq_time"] == "0830" and fires[0]["frp"] == "14.2"

xml = "<ListBucketResult xmlns='x'><Contents><Key>ABI/a.nc</Key></Contents></ListBucketResult>"
assert satellite.goes_result(xml) == ["ABI/a.nc"]

try:
    satellite.bounds({"bbox": [-181, -20, 20, 20]})
    raise AssertionError("invalid bbox accepted")
except ValueError:
    pass

print("satellite: ok")
