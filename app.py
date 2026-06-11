import os
import time
import logging
import requests
from flask import Flask, render_template, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
CKAN_ACTION_BASE  = os.getenv("CKAN_ACTION_BASE",       "https://data.gov.sg/api/action")
AVAILABILITY_URL  = os.getenv("AVAILABILITY_URL",       "https://api.data.gov.sg/v1/transport/carpark-availability")
RESOURCE_ID       = os.getenv("RESOURCE_ID",            "d_23f946fa557947f93a8043bbef41dd09")
APP_TITLE         = os.getenv("APP_TITLE",              "Singapore Carpark Map")
FETCH_LIMIT       = int(os.getenv("FETCH_LIMIT",        "5000"))
MAX_RECORDS       = int(os.getenv("MAX_RECORDS",        "20000"))
CACHE_TTL         = int(os.getenv("CACHE_TTL_SECONDS",  "21600"))   # 6 h — static info
AVAIL_CACHE_TTL   = int(os.getenv("AVAIL_CACHE_TTL_SECONDS", "60")) # 1 min — live data
HTTP_TIMEOUT      = int(os.getenv("HTTP_TIMEOUT_SECONDS","20"))
DATA_GOV_API_KEY  = os.getenv("DATA_GOV_API_KEY",       "")         # optional

DATA_URL = f"{CKAN_ACTION_BASE}/datastore_search"

# ── In-process caches ─────────────────────────────────────────────────────────
_info_cache:  dict = {"rows": None, "ts": 0.0}
_avail_cache: dict = {"data": None, "ts": 0.0, "timestamp": ""}


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _api_headers() -> dict:
    h = {"Accept": "application/json"}
    if DATA_GOV_API_KEY:
        h["x-api-key"] = DATA_GOV_API_KEY
    return h


# ── SVY21 → WGS84 conversion ──────────────────────────────────────────────────
# Based on the SVY21 technical reference published by SLA.

def svy21_to_wgs84(northing: float, easting: float) -> tuple[float, float]:
    """Convert SVY21 (N, E) to (latitude, longitude) in WGS84."""
    # Ellipsoid & projection constants
    a   = 6378137.0          # semi-major axis
    f   = 1 / 298.257223563  # flattening
    b   = a * (1 - f)
    e2  = 2 * f - f ** 2
    e_p = (a ** 2 - b ** 2) / b ** 2

    # Projection origin
    lat0 = 1.366666     # degrees
    lon0 = 103.833333   # degrees
    N0   = 38744.572    # false northing
    E0   = 28001.642    # false easting
    k0   = 1.0          # scale factor

    lat0_r = lat0 * (3.14159265358979 / 180)
    lon0_r = lon0 * (3.14159265358979 / 180)

    import math
    n_val = (a - b) / (a + b)
    G = a * (1 - n_val) * (
        1 - n_val**2 / 4 - 3 * n_val**4 / 64
    ) * math.pi / 180

    def meridian_arc(lat_r):
        return a * (
            (1 - e2/4 - 3*e2**2/64 - 5*e2**3/256) * lat_r
            - (3*e2/8 + 3*e2**2/32 + 45*e2**3/1024) * math.sin(2*lat_r)
            + (15*e2**2/256 + 45*e2**3/1024) * math.sin(4*lat_r)
            - (35*e2**3/3072) * math.sin(6*lat_r)
        )

    M0 = meridian_arc(lat0_r)
    M  = M0 + (northing - N0) / k0

    mu = M / (a * (1 - e2/4 - 3*e2**2/64 - 5*e2**3/256))

    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    lat1 = (mu
            + (3*e1/2 - 27*e1**3/32) * math.sin(2*mu)
            + (21*e1**2/16 - 55*e1**4/32) * math.sin(4*mu)
            + (151*e1**3/96) * math.sin(6*mu)
            + (1097*e1**4/512) * math.sin(8*mu))

    sin_lat1 = math.sin(lat1)
    cos_lat1 = math.cos(lat1)
    tan_lat1 = math.tan(lat1)

    N1  = a / math.sqrt(1 - e2 * sin_lat1**2)
    T1  = tan_lat1 ** 2
    C1  = e_p * cos_lat1 ** 2
    R1  = a * (1 - e2) / (1 - e2 * sin_lat1**2) ** 1.5
    D   = (easting - E0) / (N1 * k0)

    lat = lat1 - (N1 * tan_lat1 / R1) * (
        D**2/2
        - (5 + 3*T1 + 10*C1 - 4*C1**2 - 9*e_p) * D**4/24
        + (61 + 90*T1 + 298*C1 + 45*T1**2 - 252*e_p - 3*C1**2) * D**6/720
    )
    lon = lon0_r + (
        D
        - (1 + 2*T1 + C1) * D**3/6
        + (5 - 2*C1 + 28*T1 - 3*C1**2 + 8*e_p + 24*T1**2) * D**5/120
    ) / cos_lat1

    return math.degrees(lat), math.degrees(lon)


# ── Static carpark info (long TTL) ───────────────────────────────────────────

def fetch_page(offset: int, limit: int) -> list[dict]:
    r = requests.get(
        DATA_URL,
        params={"resource_id": RESOURCE_ID, "limit": limit, "offset": offset},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["result"]["records"]


def fetch_all_records() -> list[dict]:
    all_rows: list[dict] = []
    offset = 0
    while len(all_rows) < MAX_RECORDS:
        page = fetch_page(offset, FETCH_LIMIT)
        if not page:
            break
        all_rows.extend(page)
        logger.info("Fetched %d records so far (offset=%d)", len(all_rows), offset)
        if len(page) < FETCH_LIMIT:
            break
        offset += FETCH_LIMIT

    for row in all_rows:
        # Try pre-converted lon/lat first; fall back to SVY21 conversion
        lon = safe_float(row.get("longitude"))
        lat = safe_float(row.get("latitude"))
        if lat is None or lon is None:
            x = safe_float(row.get("x_coord"))
            y = safe_float(row.get("y_coord"))
            if x is not None and y is not None:
                try:
                    lat, lon = svy21_to_wgs84(y, x)
                except Exception:
                    lat, lon = None, None
        row["longitude_translated"] = lon
        row["latitude_translated"]  = lat

    return all_rows


def get_rows() -> list[dict]:
    now = time.monotonic()
    if _info_cache["rows"] is None or (now - _info_cache["ts"]) > CACHE_TTL:
        logger.info("Info cache miss — fetching from data.gov.sg")
        try:
            rows = fetch_all_records()
            if rows:
                _info_cache["rows"] = rows
                _info_cache["ts"]   = now
                logger.info("Info cache updated: %d records", len(rows))
            else:
                logger.warning("Fetch returned 0 records; keeping stale cache")
        except Exception as exc:
            logger.error("Info fetch failed: %s", exc)
            if _info_cache["rows"] is None:
                _info_cache["rows"] = []
    return _info_cache["rows"]


# ── Live availability (short TTL) ─────────────────────────────────────────────

def fetch_availability() -> tuple[dict, str]:
    r = requests.get(
        AVAILABILITY_URL,
        headers=_api_headers(),
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()

    items = payload.get("items", [])
    if not items:
        return {}, ""

    snapshot     = items[0]
    timestamp    = snapshot.get("timestamp", "")
    carpark_data = snapshot.get("carpark_data", [])

    result: dict = {}
    for entry in carpark_data:
        cp_no = entry.get("carpark_number", "").strip().upper()
        if not cp_no:
            continue
        # Iterate over the nested carpark_info list
        for lot in entry.get("carpark_info", []):
            lot_type = lot.get("lot_type", "?")
            result.setdefault(cp_no, {})[lot_type] = {
                "lots_available": int(lot.get("lots_available", 0)),
                "total_lots":     int(lot.get("total_lots",     0)),
            }

    return result, timestamp


def get_availability() -> tuple[dict, str]:
    now = time.monotonic()
    if _avail_cache["data"] is None or (now - _avail_cache["ts"]) > AVAIL_CACHE_TTL:
        logger.info("Availability cache miss — fetching live data")
        try:
            data, ts = fetch_availability()
            if data:
                _avail_cache["data"]      = data
                _avail_cache["ts"]        = now
                _avail_cache["timestamp"] = ts
                logger.info("Availability cache updated: %d carparks, ts=%s",
                            len(data), ts)
            else:
                logger.warning("Availability fetch returned empty data; keeping stale")
        except Exception as exc:
            logger.error("Availability fetch failed: %s", exc)
            if _avail_cache["data"] is None:
                _avail_cache["data"]      = {}
                _avail_cache["timestamp"] = ""
    return _avail_cache["data"], _avail_cache["timestamp"]


# ── Availability summary helper ───────────────────────────────────────────────

def summarise_availability(cp_avail: dict | None) -> dict:
    if not cp_avail:
        return {
            "avail_cars": None, "total_cars": None,
            "avail_heavy": None, "total_heavy": None,
            "avail_moto": None, "total_moto": None,
            "avail_total": None, "total_lots": None,
            "pct_available": None,
        }

    def _get(lt):
        d = cp_avail.get(lt, {})
        return d.get("lots_available"), d.get("total_lots")

    ca, tc   = _get("C")
    ha, th   = _get("H")
    ya, ty   = _get("Y")
    sa, ts_  = _get("S")

    def _add(a, b):
        if a is None and b is None:
            return None
        return (a or 0) + (b or 0)

    ma = _add(ya, sa)
    mt = _add(ty, ts_)

    avail_total = _add(_add(ca, ha), ma)
    total_lots  = _add(_add(tc, th), mt)

    pct = None
    if avail_total is not None and total_lots and total_lots > 0:
        pct = round(avail_total / total_lots * 100, 1)

    return {
        "avail_cars":    ca,  "total_cars":  tc,
        "avail_heavy":   ha,  "total_heavy": th,
        "avail_moto":    ma,  "total_moto":  mt,
        "avail_total":   avail_total,
        "total_lots":    total_lots,
        "pct_available": pct,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    rows    = get_rows()
    columns = list(rows[0].keys()) if rows else []

    translated = ["longitude_translated", "latitude_translated"]
    display_columns = [c for c in columns if c not in translated] + translated

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        rows=rows,
        column_keys=display_columns,
        lon_t_key="longitude_translated",
        lat_t_key="latitude_translated",
        map_center=[103.8198, 1.3521],
        total=len(rows),
    )


@app.route("/api/availability")
def api_availability():
    avail, ts = get_availability()
    carparks = {cp: summarise_availability(lots) for cp, lots in avail.items()}
    return jsonify({"timestamp": ts, "carparks": carparks})


if __name__ == "__main__":
    app.run(debug=True)
