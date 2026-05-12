import os
import time
import threading
import math
import requests
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify


def env(name, default):
    v = os.getenv(name)
    return default if not v else v


APP_TITLE = env("APP_TITLE", "Singapore Carpark Info Map")
RESOURCE_ID = env("RESOURCE_ID", "d_23f946fa557947f93a8043bbef41dd09")
CKAN_ACTION_BASE = env("CKAN_ACTION_BASE", "https://data.gov.sg/api/action")
FETCH_LIMIT = int(env("FETCH_LIMIT", 5000))
MAX_RECORDS = int(env("MAX_RECORDS", 20000))
CACHE_TTL_SECONDS = int(env("CACHE_TTL_SECONDS", 21600))
DISPLAY_MAX_ROWS = int(env("DISPLAY_MAX_ROWS", 2000))
HTTP_TIMEOUT_SECONDS = int(env("HTTP_TIMEOUT_SECONDS", 20))

# Output columns (will be appended if not already present)
OUT_LAT_COL = "latitude"
OUT_LON_COL = "longitude"

# Auto-detect SVY21 input columns (Easting/Northing in metres)
X_CANDIDATES = ["x_coord", "x", "easting", "east", "X_COORD", "X", "EASTING", "EAST"]
Y_CANDIDATES = ["y_coord", "y", "northing", "north", "Y_COORD", "Y", "NORTHING", "NORTH"]

app = Flask(__name__)
_cache = {}
_cache_lock = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_all():
    records = []
    offset = 0
    total = None

    while True:
        r = requests.get(
            CKAN_ACTION_BASE + "/datastore_search",
            params={
                "resource_id": RESOURCE_ID,
                "limit": FETCH_LIMIT,
                "offset": offset
            },
            timeout=HTTP_TIMEOUT_SECONDS
        )
        r.raise_for_status()
        result = r.json()["result"]

        if total is None:
            total = result.get("total", 0)

        batch = result.get("records", [])
        records.extend(batch)
        offset += len(batch)

        if offset >= total or len(records) >= MAX_RECORDS:
            break

    return records[:MAX_RECORDS], total


def find_column_case_insensitive(columns, candidates):
    # returns actual column name from dataset that matches any candidate (case-insensitive)
    lc_map = {c.lower(): c for c in columns}
    for cand in candidates:
        hit = lc_map.get(cand.lower())
        if hit:
            return hit
    return None


def safe_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# SVY21 (EPSG:3414) inverse Transverse Mercator to WGS84 lat/lon (EPSG:4326)
# Uses parameters explicitly stated in SVY21 specs:
# - Central Meridian: 103°50'00"E
# - Latitude of Origin: 1°22'00"N
# - False Easting: 28001.642 m
# - False Northing: 38744.572 m
# - Scale Factor at CM: 1.000
# - Ellipsoid: WGS84 a=6378137, inv_f=298.257223563
def svy21_to_wgs84(easting, northing):
    # WGS84 ellipsoid
    a = 6378137.0
    inv_f = 298.257223563
    f = 1.0 / inv_f
    b = a * (1.0 - f)

    e2 = (a * a - b * b) / (a * a)
    ep2 = e2 / (1.0 - e2)

    # SVY21 projection params
    lat0 = math.radians(1.3666666666666667)      # 1°22'00"N
    lon0 = math.radians(103.83333333333333)      # 103°50'00"E
    FE = 28001.642
    FN = 38744.572
    k0 = 1.0

    # Remove false origin and scale
    x = (easting - FE) / k0
    y = (northing - FN) / k0

    # Meridional arc
    e4 = e2 * e2
    e6 = e4 * e2

    def meridional_arc(phi):
        A0 = 1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256
        A2 = 3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024
        A4 = 15 * e4 / 256 + 45 * e6 / 1024
        A6 = 35 * e6 / 3072
        return a * (A0 * phi - A2 * math.sin(2 * phi) + A4 * math.sin(4 * phi) - A6 * math.sin(6 * phi))

    M0 = meridional_arc(lat0)
    M = M0 + y

    # Footpoint latitude
    mu = M / (a * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    J1 = 3 * e1 / 2 - 27 * (e1 ** 3) / 32
    J2 = 21 * (e1 ** 2) / 16 - 55 * (e1 ** 4) / 32
    J3 = 151 * (e1 ** 3) / 96
    J4 = 1097 * (e1 ** 4) / 512

    phi1 = mu + J1 * math.sin(2 * mu) + J2 * math.sin(4 * mu) + J3 * math.sin(6 * mu) + J4 * math.sin(8 * mu)

    sin1 = math.sin(phi1)
    cos1 = math.cos(phi1)
    tan1 = math.tan(phi1)

    N1 = a / math.sqrt(1 - e2 * sin1 * sin1)
    R1 = a * (1 - e2) / ((1 - e2 * sin1 * sin1) ** 1.5)
    T1 = tan1 * tan1
    C1 = ep2 * cos1 * cos1
    D = x / N1

    # Latitude
    lat = phi1 - (N1 * tan1 / R1) * (
        (D * D) / 2
        - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * (D ** 4) / 24
        + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) * (D ** 6) / 720
    )

    # Longitude
    lon = lon0 + (
        D
        - (1 + 2 * T1 + C1) * (D ** 3) / 6
        + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * (D ** 5) / 120
    ) / cos1

    # Return in EPSG:4326 axis order (lat, lon), matching your pyproj sample
    return math.degrees(lat), math.degrees(lon)


def add_lat_lon_columns(records, columns):
    # Detect input SVY21 columns
    x_col = find_column_case_insensitive(columns, X_CANDIDATES)
    y_col = find_column_case_insensitive(columns, Y_CANDIDATES)

    # Append output columns if not present
    if OUT_LAT_COL not in columns:
        columns = columns + [OUT_LAT_COL]
    if OUT_LON_COL not in columns:
        columns = columns + [OUT_LON_COL]

    # If we can't find x/y, just return with blanks for lat/lon
    if not x_col or not y_col:
        new_records = []
        for r in records:
            rr = dict(r)
            if OUT_LAT_COL not in rr:
                rr[OUT_LAT_COL] = ""
            if OUT_LON_COL not in rr:
                rr[OUT_LON_COL] = ""
            new_records.append(rr)
        return new_records, columns, None, None

    new_records = []
    for r in records:
        rr = dict(r)
        x = safe_float(rr.get(x_col))
        y = safe_float(rr.get(y_col))
        if x is None or y is None:
            rr[OUT_LAT_COL] = ""
            rr[OUT_LON_COL] = ""
        else:
            lat, lon = svy21_to_wgs84(x, y)
            rr[OUT_LAT_COL] = "{0:.6f}".format(lat)
            rr[OUT_LON_COL] = "{0:.6f}".format(lon)
        new_records.append(rr)

    return new_records, columns, OUT_LAT_COL, OUT_LON_COL


def get_data(refresh=False):
    with _cache_lock:
        if not refresh and _cache.get("expires", 0) > time.time():
            return _cache

    records, total = fetch_all()
    columns = [k for k in records[0] if not k.startswith("_")] if records else []

    # Add computed latitude/longitude columns from x_coord/y_coord
    records2, columns2, lat_col, lon_col = add_lat_lon_columns(records, columns)

    with _cache_lock:
        _cache.update({
            "records": records2,
            "columns": columns2,
            "lat_col": lat_col,
            "lon_col": lon_col,
            "total": total,
            "fetched": now_iso(),
            "expires": time.time() + CACHE_TTL_SECONDS
        })

    return _cache


@app.route("/", methods=["GET"])
def index():
    q = (request.args.get("q") or "").lower()
    refresh = request.args.get("refresh") == "1"

    data = get_data(refresh)
    rows = data["records"]
    columns = data["columns"]
    lat_col = data.get("lat_col")
    lon_col = data.get("lon_col")

    if q:
        rows = [r for r in rows if any(q in str(v).lower() for v in r.values())]

    rows = rows[:DISPLAY_MAX_ROWS]

    # Build Google Maps URL using up to first 20 unique computed lat/lon locations
    seen = set()
    points = []

    if lat_col and lon_col:
        for r in rows:
            lat = safe_float(r.get(lat_col))
            lon = safe_float(r.get(lon_col))
            if lat is None or lon is None:
                continue
            key = (round(lat, 6), round(lon, 6))
            if key not in seen:
                seen.add(key)
                points.append(str(lat) + "," + str(lon))
            if len(points) == 20:
                break

    map_url = None
    if len(points) >= 2:
        map_url = "https://www.google.com/maps/dir/" + "/".join(points)

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        resource_id=RESOURCE_ID,
        fetched_at=data["fetched"],
        total_ckan=data["total"],
        columns=columns,
        rows=rows,
        map_url=map_url,
        map_count=len(points),
        q=q
    )


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True)
