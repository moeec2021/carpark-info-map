import os
import time
import math
import csv
import io
import requests
from datetime import datetime, timezone
from flask import Flask, render_template, request, Response, jsonify

APP_TITLE = os.getenv("APP_TITLE", "Singapore Carpark Map")

# CKAN carpark info datasets
CKAN_ACTION_BASE = os.getenv("CKAN_ACTION_BASE", "https://data.gov.sg/api/action")
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "5000"))
MAX_RECORDS = int(os.getenv("MAX_RECORDS", "20000"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "21600"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))

# Availability API (optional API key)
DATA_GOV_SG_API_KEY = os.getenv("DATA_GOV_SG_API_KEY", "").strip()
AVAIL_TTL_SECONDS = int(os.getenv("AVAIL_TTL_SECONDS", "60"))

# HDB + JTC carpark info datasets
DATASETS = [
    {"resource_id": "d_23f946fa557947f93a8043bbef41dd09", "label": "HDB"},
    {"resource_id": "d_3b0c377cde41041c93f893d0a92e9fe7", "label": "JTC"},
]

X_COL = "x_coord"
Y_COL = "y_coord"
LON_T = "longitude_translated"
LAT_T = "latitude_translated"
SRC_COL = "data_source"

# Availability columns
AVAIL_TS = "availability_timestamp"
LOTS_AVAIL_C = "lots_available_C"
TOTAL_LOTS_C = "total_lots_C"
LOTS_AVAIL_H = "lots_available_H"
TOTAL_LOTS_H = "total_lots_H"
LOTS_AVAIL_S = "lots_available_S"
TOTAL_LOTS_S = "total_lots_S"
LOTS_AVAIL_Y = "lots_available_Y"
TOTAL_LOTS_Y = "total_lots_Y"

AVAIL_COLS = [
    AVAIL_TS,
    LOTS_AVAIL_C, TOTAL_LOTS_C,
    LOTS_AVAIL_H, TOTAL_LOTS_H,
    LOTS_AVAIL_S, TOTAL_LOTS_S,
    LOTS_AVAIL_Y, TOTAL_LOTS_Y,
]

INTERNAL_KEYS = {"_id", "_full_text"}

app = Flask(__name__)

_cache = {
    "expires_at": 0.0,
    "fetched_at": "",
    "total": 0,
    "columns": [],
    "rows": [],
}

_avail_cache = {
    "expires_at": 0.0,
    "timestamp": "",
    "map": {},  # carpark_number -> { lot_type: (avail, total) }
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

def safe_int(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None

def datastore_search_url():
    return CKAN_ACTION_BASE.rstrip("/") + "/datastore_search"

def find_key_case_insensitive(keys, candidates):
    lk = {k.lower(): k for k in keys}
    for c in candidates:
        hit = lk.get(c.lower())
        if hit:
            return hit
    return None

# SVY21 (EPSG:3414) inverse Transverse Mercator -> WGS84 (EPSG:4326)
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

def fetch_dataset(resource_id):
    url = datastore_search_url()
    offset = 0
    rows = []
    fields = []
    total = 0

    while True:
        resp = requests.get(
            url,
            params={"resource_id": resource_id, "limit": FETCH_LIMIT, "offset": offset},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise RuntimeError("CKAN datastore_search returned success=false")

        result = payload.get("result") or {}
        if offset == 0:
            fields = result.get("fields") or []
            total = int(result.get("total") or 0)

        batch = result.get("records") or []
        if not batch:
            break

        rows.extend(batch)
        offset += len(batch)

        if len(rows) >= MAX_RECORDS:
            rows = rows[:MAX_RECORDS]
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

    if not cols and rows:
        cols = [k for k in rows[0].keys() if k not in INTERNAL_KEYS and not k.startswith("_")]

    return rows, cols

def compute_translated_and_normalize_xy(rows):
    x_candidates = ["x_coord", "x", "easting", "east", "xcoord", "x-coordinate", "xcoordinate"]
    y_candidates = ["y_coord", "y", "northing", "north", "ycoord", "y-coordinate", "ycoordinate"]

    for r in rows:
        keys = list(r.keys())
        x_key = find_key_case_insensitive(keys, x_candidates)
        y_key = find_key_case_insensitive(keys, y_candidates)

        if x_key and X_COL not in r:
            r[X_COL] = r.get(x_key, "")
        if y_key and Y_COL not in r:
            r[Y_COL] = r.get(y_key, "")

        x = safe_float(r.get(X_COL))
        y = safe_float(r.get(Y_COL))

        if x is None or y is None:
            r[LON_T] = ""
            r[LAT_T] = ""
        else:
            lon, lat = svy21_to_wgs84(x, y)
            r[LON_T] = f"{lon:.6f}"
            r[LAT_T] = f"{lat:.6f}"

def fetch_availability(force_refresh=False):
    now = time.time()
    if (not force_refresh) and now < _avail_cache["expires_at"]:
        return _avail_cache

    url = "https://api.data.gov.sg/v1/transport/carpark-availability"
    headers = {}
    if DATA_GOV_SG_API_KEY:
        headers["x-api-key"] = DATA_GOV_SG_API_KEY

    amap = {}
    ts = ""

    try:
        resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()

        items = payload.get("items") or []
        if items:
            first = items[0] or {}
            ts = first.get("timestamp") or ""

            carpark_data = first.get("carpark_data") or []
            for entry in carpark_data:
                cpn = (
                    entry.get("carpark_number")
                    or entry.get("carpark_no")
                    or entry.get("car_park_no")
                    or ""
                )
                if not cpn:
                    continue

                info_list = entry.get("carpark_info") or []
                if not isinstance(info_list, list):
                    continue

                if cpn not in amap:
                    amap[cpn] = {}

                for lot in info_list:
                    if not isinstance(lot, dict):
                        continue
                    lt = (lot.get("lot_type") or "").strip()
                    avail = safe_int(lot.get("lots_available"))
                    total = safe_int(lot.get("total_lots"))
                    if lt:
                        amap[cpn][lt] = (avail, total)

    except Exception:
        amap = {}
        ts = ""

    _avail_cache.update({
        "expires_at": now + AVAIL_TTL_SECONDS,
        "timestamp": ts,
        "map": amap
    })
    return _avail_cache

def apply_availability(rows):
    avail = fetch_availability(force_refresh=False)
    ts = avail.get("timestamp", "")
    amap = avail.get("map", {})

    cp_candidates = ["car_park_no", "carpark_number", "car_park_number", "carpark_no", "carparkno", "carpark"]
    for r in rows:
        for c in AVAIL_COLS:
            r[c] = ""

        keys = list(r.keys())
        cp_key = find_key_case_insensitive(keys, cp_candidates)
        if not cp_key:
            continue

        cp_no = str(r.get(cp_key, "")).strip()
        if not cp_no:
            continue

        lots = amap.get(cp_no)
        if not lots:
            continue

        r[AVAIL_TS] = ts

        def set_lot(lt, avail_key, total_key):
            at = lots.get(lt)
            if not at:
                return
            a, t = at
            r[avail_key] = "" if a is None else str(a)
            r[total_key] = "" if t is None else str(t)

        set_lot("C", LOTS_AVAIL_C, TOTAL_LOTS_C)
        set_lot("H", LOTS_AVAIL_H, TOTAL_LOTS_H)
        set_lot("S", LOTS_AVAIL_S, TOTAL_LOTS_S)
        set_lot("Y", LOTS_AVAIL_Y, TOTAL_LOTS_Y)

def build_merged_columns(all_cols):
    base = [c for c in all_cols if c not in (X_COL, Y_COL, LON_T, LAT_T, SRC_COL, *AVAIL_COLS)]
    base += AVAIL_COLS
    base += [X_COL, Y_COL, LON_T, LAT_T, SRC_COL]
    return base

def get_data(force_refresh=False):
    now = time.time()
    if (not force_refresh) and _cache["rows"] and now < _cache["expires_at"]:
        return _cache

    fetch_availability(force_refresh=True if force_refresh else False)

    merged_rows = []
    merged_cols_set = set()

    for ds in DATASETS:
        rid = ds["resource_id"]
        label = ds["label"]

        rows, cols = fetch_dataset(rid)
        for c in cols:
            merged_cols_set.add(c)

        for r in rows:
            r[SRC_COL] = label

        compute_translated_and_normalize_xy(rows)
        apply_availability(rows)

        for c in (X_COL, Y_COL, LON_T, LAT_T, SRC_COL, *AVAIL_COLS):
            merged_cols_set.add(c)

        merged_rows.extend(rows)

    merged_cols = build_merged_columns(list(merged_cols_set))

    _cache.update({
        "expires_at": now + CACHE_TTL_SECONDS,
        "fetched_at": now_iso(),
        "total": len(merged_rows),
        "columns": merged_cols,
        "rows": merged_rows,
    })
    return _cache

def filter_rows(rows, q):
    if not q:
        return rows
    qq = q.lower().strip()
    if qq == "":
        return rows
    out = []
    for r in rows:
        for v in r.values():
            if v is None:
                continue
            if qq in str(v).lower():
                out.append(r)
                break
    return out

@app.route("/")
def index():
    q = request.args.get("q", "")
    refresh = request.args.get("refresh") == "1"

    data = get_data(force_refresh=refresh)
    rows = filter_rows(data["rows"], q)

    pts = []
    for r in rows:
        lon = safe_float(r.get(LON_T))
        lat = safe_float(r.get(LAT_T))
        if lon is not None and lat is not None:
            pts.append([lon, lat])
        if len(pts) >= 50:
            break

    if pts:
        avg_lon = sum(p[0] for p in pts) / len(pts)
        avg_lat = sum(p[1] for p in pts) / len(pts)
        map_center = [avg_lon, avg_lat]
    else:
        map_center = [103.8198, 1.3521]

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        resource_id=" + ".join([d["label"] for d in DATASETS]),
        fetched_at=data["fetched_at"],
        total_ckan=data["total"],
        q=q,
        rows=rows,
        column_keys=data["columns"],
        lon_t_key=LON_T,
        lat_t_key=LAT_T,
        map_center=map_center,
    )

@app.route("/download.csv")
def download_csv():
    q = request.args.get("q", "")
    data = get_data(force_refresh=False)
    rows = filter_rows(data["rows"], q)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(data["columns"])
    for r in rows:
        writer.writerow([r.get(c, "") for c in data["columns"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=carparks_with_availability.csv"},
    )

@app.route("/healthz")
def healthz():
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
