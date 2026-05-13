import os
import time
import threading
import math
import requests
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify


def env_str(name, default):
    v = os.getenv(name)
    return default if v is None or v == "" else v


def env_int(name, default):
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


APP_TITLE = env_str("APP_TITLE", "Singapore Carpark Info Map (OneMap + MapLibre)")
RESOURCE_ID = env_str("RESOURCE_ID", "d_23f946fa557947f93a8043bbef41dd09")
CKAN_ACTION_BASE = env_str("CKAN_ACTION_BASE", "https://data.gov.sg/api/action")

FETCH_LIMIT = env_int("FETCH_LIMIT", 5000)
MAX_RECORDS = env_int("MAX_RECORDS", 20000)
CACHE_TTL_SECONDS = env_int("CACHE_TTL_SECONDS", 21600)
DISPLAY_MAX_ROWS = env_int("DISPLAY_MAX_ROWS", 20000)  # allow full dataset; tune if needed
HTTP_TIMEOUT_SECONDS = env_int("HTTP_TIMEOUT_SECONDS", 20)

# New computed fields (keys in the record dict)
LON_T_KEY = "longitude_translated"
LAT_T_KEY = "latitude_translated"

# Move these to the far right (if present)
X_KEYS = ["x_coord", "x", "easting", "east", "xcoord", "x-coordinate", "xcoordinate"]
Y_KEYS = ["y_coord", "y", "northing", "north", "ycoord", "y-coordinate", "ycoordinate"]

# Desired columns you explicitly requested (will be pulled in automatically if present)
PREFERRED_COLS = [
    "car_park_no",
    "address",
    "x_coord",
    "y_coord",
    "car_park_type",
    "type_of_parking_system",
    "short_term_parking",
    "free_parking",
]

INTERNAL_KEYS = {"_id", "_full_text"}

app = Flask(__name__)

_cache_lock = threading.Lock()
_cache = {
    "expires_at": 0.0,
    "fetched_at": "",
    "total_ckan": 0,
    "records": [],
    "columns_raw": [],  # columns from CKAN (excluding internal)
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


def find_col_case_insensitive(columns, candidates):
    # columns are exact keys; candidates are possible names
    lc_map = {c.lower(): c for c in columns}
    for cand in candidates:
        hit = lc_map.get(cand.lower())
        if hit:
            return hit
    return None


def datastore_search_url():
    base = CKAN_ACTION_BASE.rstrip("/")
    return base + "/datastore_search"


def fetch_all_from_ckan():
    url = datastore_search_url()
    offset = 0
    records = []
    total = 0
    fields = []

    while True:
        r = requests.get(
            url,
            params={
                "resource_id": RESOURCE_ID,
                "limit": FETCH_LIMIT,
                "offset": offset,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        payload = r.json()
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

    # derive column order from CKAN fields, exclude internal keys
    cols = []
    for f in fields:
        fid = f.get("id")
        if not fid:
            continue
        if fid in INTERNAL_KEYS:
            continue
        if fid.startswith("_"):
            continue
        cols.append(fid)

    # fallback if fields missing
    if not cols and records:
        for k in records[0].keys():
            if k in INTERNAL_KEYS or k.startswith("_"):
                continue
            cols.append(k)

    return records, total, cols


# SVY21 (EPSG:3414) inverse Transverse Mercator -> WGS84 (EPSG:4326)
# Parameters: CM=103°50'00"E, Lat0=1°22'00"N, FE=28001.642, FN=38744.572, k0=1.000, WGS84 ellipsoid
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

    return math.degrees(lat), math.degrees(lon)


def add_translated_lonlat(records, columns):
    # Find x/y columns in the dataset (case-insensitive)
    x_col = find_col_case_insensitive(columns, X_KEYS)
    y_col = find_col_case_insensitive(columns, Y_KEYS)

    out = []
    for r in records:
        rr = dict(r)

        x = safe_float(rr.get(x_col)) if x_col else None
        y = safe_float(rr.get(y_col)) if y_col else None

        if x is None or y is None:
            rr[LON_T_KEY] = ""
            rr[LAT_T_KEY] = ""
        else:
            lat, lon = svy21_to_wgs84(x, y)
            rr[LON_T_KEY] = "{0:.6f}".format(lon)
            rr[LAT_T_KEY] = "{0:.6f}".format(lat)

        out.append(rr)

    return out, x_col, y_col


def build_display_columns(columns_raw, x_col, y_col):
    # Keep ALL original dataset columns, but:
    # 1) Put preferred cols first (if present)
    # 2) Put remaining (excluding x/y) next
    # 3) Put x/y at far right
    # 4) Append translated lon/lat at far right
    cols = list(columns_raw)

    # Remove any internal keys just in case
    cols = [c for c in cols if c not in INTERNAL_KEYS and not c.startswith("_")]

    # Determine actual x/y names present
    x_name = x_col
    y_name = y_col

    # Make an ordered set
    ordered = []

    # preferred, but only those that exist
    for p in PREFERRED_COLS:
        if p in cols and p not in ordered and p not in (x_name, y_name):
            ordered.append(p)

    # then everything else except x/y
    for c in cols:
        if c in (x_name, y_name):
            continue
        if c in ordered:
            continue
        ordered.append(c)

    # then x/y at the end if they exist
    if x_name and x_name in cols:
        ordered.append(x_name)
    else:
        x_name = None

    if y_name and y_name in cols:
        ordered.append(y_name)
    else:
        y_name = None

    # append translated columns at far right (display labels handled in template)
    ordered.append(LON_T_KEY)
    ordered.append(LAT_T_KEY)

    return ordered, x_name, y_name


def get_cached_data(force_refresh=False):
    now = time.time()
    with _cache_lock:
        if not force_refresh and _cache["records"] and now < _cache["expires_at"]:
            return dict(_cache)

    records, total, cols = fetch_all_from_ckan()
    records2, x_col, y_col = add_translated_lonlat(records, cols)

    with _cache_lock:
        _cache["records"] = records2
        _cache["columns_raw"] = cols
        _cache["total_ckan"] = total
        _cache["fetched_at"] = now_iso()
        _cache["expires_at"] = now + CACHE_TTL_SECONDS
        _cache["x_col"] = x_col
        _cache["y_col"] = y_col

    return dict(_cache)


@app.route("/", methods=["GET"])
def index():
    q = (request.args.get("q") or "").strip().lower()
    refresh = (request.args.get("refresh") or "").strip() == "1"

    data = get_cached_data(force_refresh=refresh)

    records = data.get("records", [])
    cols_raw = data.get("columns_raw", [])
    x_col = data.get("x_col")
    y_col = data.get("y_col")

    # server-side contains filter across all fields
    if q:
        filtered = []
        for r in records:
            hit = False
            for v in r.values():
                if v is None:
                    continue
                if q in str(v).lower():
                    hit = True
                    break
            if hit:
                filtered.append(r)
        records = filtered

    records = records[:DISPLAY_MAX_ROWS]

    display_cols, x_name, y_name = build_display_columns(cols_raw, x_col, y_col)

    # Build map markers from first 10 translated points
    pts = []
    for r in records[:10]:
        lon = safe_float(r.get(LON_T_KEY))
        lat = safe_float(r.get(LAT_T_KEY))
        if lon is None or lat is None:
            continue
        pts.append((lon, lat))

    if pts:
        avg_lon = sum(p[0] for p in pts) / len(pts)
        avg_lat = sum(p[1] for p in pts) / len(pts)
        map_center = (avg_lat, avg_lon)  # (lat, lon)
    else:
        map_center = (1.3521, 103.8198)

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        resource_id=RESOURCE_ID,
        fetched_at=data.get("fetched_at", ""),
        total_ckan=data.get("total_ckan", 0),
        q=q,
        rows=records,
        column_keys=display_cols,
        x_col=x_name,
        y_col=y_name,
        lon_t_key=LON_T_KEY,
        lat_t_key=LAT_T_KEY,
        map_center=map_center,
        map_points=pts,
    )


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True)
