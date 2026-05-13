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

# Output columns (always present in the rendered table)
LAT_OUT = "latitude"
LON_OUT = "longitude"

# Detect SVY21 input columns (Easting / Northing) commonly used in datasets
X_CANDIDATES = ["x_coord", "x", "easting", "east", "xcoord", "x-coordinate", "xcoordinate"]
Y_CANDIDATES = ["y_coord", "y", "northing", "north", "ycoord", "y-coordinate", "ycoordinate"]

app = Flask(__name__)

_cache = {}
_cache_lock = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def find_col_case_insensitive(columns, candidates):
    lc_map = {c.lower(): c for c in columns}
    for cand in candidates:
        hit = lc_map.get(cand.lower())
        if hit:
            return hit
    return None


# SVY21 (EPSG:3414) inverse Transverse Mercator -> WGS84 (EPSG:4326)
# Uses SVY21 parameters: CM=103°50'00"E, Lat0=1°22'00"N, FE=28001.642, FN=38744.572, k0=1.000
# and WGS84 ellipsoid a=6378137, inv_f=298.257223563.
# These parameters are explicitly listed in <File>REPORT_NO._035-23_GEONAMICS_BATHY(REV.3)[1].pdf</File>. 

def svy21_to_wgs84(easting, northing):
    a = 6378137.0
    inv_f = 298.257223563
    f = 1.0 / inv_f
    b = a * (1.0 - f)

    e2 = (a * a - b * b) / (a * a)
    ep2 = e2 / (1.0 - e2)

    lat0 = math.radians(1.3666666666666667)  # 1°22'00"N
    lon0 = math.radians(103.83333333333333)  # 103°50'00"E
    FE = 28001.642
    FN = 38744.572
    k0 = 1.0

    x = (easting - FE) / k0
    y = (northing - FN) / k0

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

    lat = phi1 - (N1 * tan1 / R1) * (
        (D * D) / 2
        - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * (D ** 4) / 24
        + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) * (D ** 6) / 720
    )

    lon = lon0 + (
        D
        - (1 + 2 * T1 + C1) * (D ** 3) / 6
        + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * (D ** 5) / 120
    ) / cos1

    return math.degrees(lat), math.degrees(lon)


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
        result = r.json().get("result", {})

        if total is None:
            total = int(result.get("total", 0))

        batch = result.get("records", [])
        if not batch:
            break

        records.extend(batch)
        offset += len(batch)

        if offset >= total or len(records) >= MAX_RECORDS:
            break

    return records[:MAX_RECORDS], total


def recompute_lat_lon(records, columns):
    # Always ensure latitude/longitude columns exist in the rendered table
    cols = list(columns)
    if LAT_OUT not in cols:
        cols.append(LAT_OUT)
    if LON_OUT not in cols:
        cols.append(LON_OUT)

    x_col = find_col_case_insensitive(cols, X_CANDIDATES)
    y_col = find_col_case_insensitive(cols, Y_CANDIDATES)

    out = []
    for r in records:
        rr = dict(r)

        x = safe_float(rr.get(x_col)) if x_col else None
        y = safe_float(rr.get(y_col)) if y_col else None

        if x is None or y is None:
            rr[LAT_OUT] = rr.get(LAT_OUT, "")
            rr[LON_OUT] = rr.get(LON_OUT, "")
        else:
            lat, lon = svy21_to_wgs84(x, y)
            rr[LAT_OUT] = "{0:.6f}".format(lat)
            rr[LON_OUT] = "{0:.6f}".format(lon)

        out.append(rr)

    return out, cols


def get_data(refresh=False):
    with _cache_lock:
        if not refresh and _cache.get("expires", 0) > time.time():
            return _cache

    records, total = fetch_all()
    base_cols = [k for k in records[0] if not k.startswith("_")] if records else []

    records2, cols2 = recompute_lat_lon(records, base_cols)

    with _cache_lock:
        _cache.update({
            "records": records2,
            "columns": cols2,
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

    if q:
        rows = [r for r in rows if any(q in str(v).lower() for v in r.values())]

    rows = rows[:DISPLAY_MAX_ROWS]

    # Useful info for UI (how many rows have computed lat/lon)
    computed_count = 0
    for r in rows:
        if str(r.get(LAT_OUT, "")).strip() != "" and str(r.get(LON_OUT, "")).strip() != "":
            computed_count += 1

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        resource_id=RESOURCE_ID,
        fetched_at=data["fetched"],
        total_ckan=data["total"],
        columns=data["columns"],
        rows=rows,
        q=q,
        computed_count=computed_count
    )


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True)
