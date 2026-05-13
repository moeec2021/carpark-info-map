import os
import time
import math
import requests
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ---------- Config ----------
APP_TITLE = os.getenv("APP_TITLE", "Singapore Carpark Map")
RESOURCE_ID = os.getenv("RESOURCE_ID", "d_23f946fa557947f93a8043bbef41dd09")
CKAN_ACTION_BASE = os.getenv("CKAN_ACTION_BASE", "https://data.gov.sg/api/action")

FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "5000"))
MAX_RECORDS = int(os.getenv("MAX_RECORDS", "20000"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "21600"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))

X_COL = "x_coord"
Y_COL = "y_coord"
LON_T = "longitude_translated"
LAT_T = "latitude_translated"

INTERNAL_KEYS = {"_id", "_full_text"}

_cache = {
    "expires_at": 0.0,
    "fetched_at": "",
    "total": 0,
    "columns": [],
    "records": [],
}

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

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

def datastore_search_url():
    base = CKAN_ACTION_BASE.rstrip("/")
    return base + "/datastore_search"

# ---------- SVY21 (EPSG:3414) → WGS84 (EPSG:4326) ----------
# Parameters: CM=103°50'00"E, Lat0=1°22'00"N, FE=28001.642, FN=38744.572, k0=1.0, WGS84 ellipsoid
def svy21_to_wgs84(easting, northing):
    a = 6378137.0
    inv_f = 298.257223563
    f = 1.0 / inv_f
    b = a * (1.0 - f)

    e2 = (a * a - b * b) / (a * a)
    ep2 = e2 / (1.0 - e2)

    lat0 = math.radians(1.3666666666666667)
    lon0 = math.radians(103.83333333333333)
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

    return math.degrees(lon), math.degrees(lat)

# ---------- Data fetch + cache ----------
def fetch_all_records():
    url = datastore_search_url()
    offset = 0
    records = []
    total = 0
    fields = []

    while True:
        resp = requests.get(
            url,
            params={"resource_id": RESOURCE_ID, "limit": FETCH_LIMIT, "offset": offset},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise RuntimeError("CKAN datastore_search returned success=false")

        result = payload.get("result") or {}
        if offset == 0:
            total = int(result.get("total") or 0)
            fields = result.get("fields") or []

        batch = result.get("records") or []
        if not batch:
            break

        records.extend(batch)
        offset += len(batch)

        if len(records) >= MAX_RECORDS:
            records = records[:MAX_RECORDS]
            break

        if offset >= total:
            break

    cols = []
    for f in fields:
        fid = f.get("id")
        if not fid:
            continue
        if fid in INTERNAL_KEYS or fid.startswith("_"):
            continue
        cols.append(fid)

    if not cols and records:
        cols = [k for k in records[0].keys() if k not in INTERNAL_KEYS and not k.startswith("_")]

    return records, total, cols

def compute_translated_coords(records):
    for r in records:
        x = safe_float(r.get(X_COL))
        y = safe_float(r.get(Y_COL))
        if x is None or y is None:
            r[LON_T] = ""
            r[LAT_T] = ""
        else:
            lon, lat = svy21_to_wgs84(x, y)
            r[LON_T] = f"{lon:.6f}"
            r[LAT_T] = f"{lat:.6f}"

def build_display_columns(cols):
    base = [c for c in cols if c not in (X_COL, Y_COL)]
    base += [X_COL, Y_COL, LON_T, LAT_T]
    return base

def get_data(force_refresh=False):
    now = time.time()
    if (not force_refresh) and _cache["records"] and now < _cache["expires_at"]:
        return _cache

    records, total, cols = fetch_all_records()
    compute_translated_coords(records)
    display_cols = build_display_columns(cols)

    _cache["records"] = records
    _cache["total"] = total
    _cache["columns"] = display_cols
    _cache["fetched_at"] = now_iso()
    _cache["expires_at"] = now + CACHE_TTL_SECONDS
    return _cache

# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    q = (request.args.get("q") or "").strip().lower()
    refresh = (request.args.get("refresh") or "").strip() == "1"

    data = get_data(force_refresh=refresh)
    rows = data["records"]
    cols = data["columns"]

    # server-side contains filter
    if q:
        filtered = []
        for r in rows:
            found = False
            for v in r.values():
                if v is None:
                    continue
                if q in str(v).lower():
                    found = True
                    break
            if found:
                filtered.append(r)
        rows = filtered

    # map points from first 10 filtered records
    pts = []
    for r in rows[:10]:
        lon = safe_float(r.get(LON_T))
        lat = safe_float(r.get(LAT_T))
        if lon is not None and lat is not None:
            pts.append([lon, lat])  # [lon, lat]

    if pts:
        avg_lon = sum(p[0] for p in pts) / len(pts)
        avg_lat = sum(p[1] for p in pts) / len(pts)
        map_center = [avg_lon, avg_lat]
    else:
        map_center = [103.8198, 1.3521]

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        resource_id=RESOURCE_ID,
        fetched_at=data["fetched_at"],
        total_ckan=data["total"],
        q=q,
        column_keys=cols,
        rows=rows,
        map_center=map_center,
        map_points=pts,
        lon_t_key=LON_T,
        lat_t_key=LAT_T,
    )

@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run()
