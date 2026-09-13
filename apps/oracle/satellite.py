"""Pure request builders and parsers for Chatter's satellite tool."""
import csv
import io
import math
import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone


GIBS_WMS = os.environ.get(
    "ORACLE_GIBS_WMS", "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi")
CDSE_STAC = os.environ.get(
    "ORACLE_CDSE_STAC", "https://stac.dataspace.copernicus.eu/v1/search")
FIRMS_AREA = os.environ.get(
    "ORACLE_FIRMS_AREA", "https://firms.modaps.eosdis.nasa.gov/api/area/csv")
GOES_BUCKET = os.environ.get(
    "ORACLE_GOES_BUCKET", "https://noaa-goes19.s3.amazonaws.com")
GEOCODE = os.environ.get(
    "ORACLE_GEOCODE", "https://geocoding-api.open-meteo.com/v1/search")

GIBS_LAYERS = {
    "natural": "MODIS_Terra_CorrectedReflectance_TrueColor",
    "natural_aqua": "MODIS_Aqua_CorrectedReflectance_TrueColor",
    "night": "VIIRS_SNPP_DayNightBand_ENCC",
    "clouds": "MODIS_Terra_Cloud_Top_Temp_Day",
    "fires": "VIIRS_SNPP_Thermal_Anomalies_375m_Night",
    "snow": "MODIS_Terra_NDSI_Snow_Cover",
    "sea_ice": "AMSR2_Sea_Ice_Concentration_12km",
}

CDSE_COLLECTIONS = {
    "optical": "sentinel-2-l2a",
    "radar": "sentinel-1-grd",
}


def bounds(args):
    """Return a validated WGS84 ``[west,south,east,north]``."""
    raw = args.get("bbox")
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        box = [float(x) for x in raw]
    else:
        lat, lon = float(args["latitude"]), float(args["longitude"])
        km = min(2500.0, max(1.0, float(args.get("radius_km") or 100.0)))
        dy = km / 111.32
        dx = km / max(1.0, 111.32 * math.cos(math.radians(lat)))
        box = [lon - dx, lat - dy, lon + dx, lat + dy]
    west, south, east, north = box
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox must be [west,south,east,north] inside WGS84")
    return [round(v, 6) for v in box]


def default_date(value=""):
    if value:
        return datetime.strptime(str(value), "%Y-%m-%d").date().isoformat()
    # Polar imagery commonly lands hours after acquisition; yesterday is the
    # newest date that is reliably complete across a whole requested box.
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def gibs_url(box, product="natural", date="", width=1024, height=768):
    layer = GIBS_LAYERS.get(product, product)
    width = min(1600, max(256, int(width)))
    height = min(1600, max(256, int(height)))
    q = urllib.parse.urlencode({
        "service": "WMS", "request": "GetMap", "version": "1.1.1",
        "layers": layer, "styles": "", "format": "image/png",
        "transparent": "false", "srs": "EPSG:4326",
        "bbox": ",".join(str(v) for v in box), "width": width,
        "height": height, "time": default_date(date),
    })
    return GIBS_WMS + "?" + q, layer


def stac_body(box, product="optical", date="", days=14, cloud=30, limit=10):
    end = datetime.strptime(default_date(date), "%Y-%m-%d").date()
    start = end - timedelta(days=min(365, max(1, int(days))))
    collection = CDSE_COLLECTIONS.get(product, product)
    body = {"collections": [collection], "bbox": box,
            "datetime": start.isoformat() + "T00:00:00Z/"
                        + end.isoformat() + "T23:59:59Z",
            "limit": min(50, max(1, int(limit)))}
    if collection == "sentinel-2-l2a":
        body["query"] = {"eo:cloud_cover": {"lte": min(100, max(0, float(cloud)))}}
    return body


def stac_result(doc):
    rows = []
    for f in (doc.get("features") or [])[:50]:
        p, assets = f.get("properties") or {}, f.get("assets") or {}
        preview = ""
        for name in ("thumbnail", "preview", "visual"):
            if isinstance(assets.get(name), dict) and assets[name].get("href"):
                preview = assets[name]["href"]
                break
        rows.append({"id": f.get("id", ""), "acquired": p.get("datetime", ""),
                     "cloud_cover": p.get("eo:cloud_cover"),
                     "platform": p.get("platform", ""), "preview": preview})
    return rows


def firms_url(key, box, source="VIIRS_SNPP_NRT", days=1, date=""):
    area = ",".join(str(v) for v in box)
    bits = [FIRMS_AREA.rstrip("/"), urllib.parse.quote(key, safe=""),
            urllib.parse.quote(source, safe=""), area,
            str(min(5, max(1, int(days))))]
    if date:
        bits.append(default_date(date))
    return "/".join(bits)


def firms_result(data, limit=100):
    rows = []
    for row in csv.DictReader(io.StringIO(data)):
        rows.append({k: row.get(k, "") for k in
                     ("latitude", "longitude", "acq_date", "acq_time",
                      "satellite", "instrument", "confidence", "frp", "daynight")})
        if len(rows) >= limit:
            break
    return rows


def goes_url(date="", hour=None, product="ABI-L2-CMIPF"):
    dt = datetime.strptime(default_date(date), "%Y-%m-%d")
    if hour is None:
        hour = 23 if date else datetime.now(timezone.utc).hour
    prefix = "%s/%s/%03d/%02d/" % (product, dt.year, dt.timetuple().tm_yday,
                                     min(23, max(0, int(hour))))
    return GOES_BUCKET + "/?" + urllib.parse.urlencode(
        {"list-type": "2", "prefix": prefix, "max-keys": 50}), prefix


def goes_result(data):
    root = ET.fromstring(data)
    keys = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "Key" and node.text:
            keys.append(node.text)
    return keys[:50]
