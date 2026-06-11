import os
import time
import logging
import requests
from flask import Flask, render_template, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
CKAN_ACTION_BASE      = os.getenv("CKAN_ACTION_BASE",       "https://data.gov.sg/api/action")
AVAILABILITY_URL      = os.getenv("AVAILABILITY_URL",       "https://api.data.gov.sg/v1/transport/carpark-availability")
RESOURCE_ID           = os.getenv("RESOURCE_ID",            "d_23f946fa557947f93a8043bbef41dd09")
APP_TITLE             = os.getenv("APP_TITLE",              "Singapore Carpark Map")
FETCH_LIMIT           = int(os.getenv("FETCH_LIMIT",        "5000"))
MAX_RECORDS           = int(os.getenv("MAX_RECORDS",        "20000"))
CACHE_TTL             = int(os.getenv("CACHE_TTL_SECONDS",  "21600"))   # 6 h — static info
AVAIL_CACHE_TTL       = int(os.getenv("AVAIL_CACHE_TTL_SECONDS", "60")) # 1 min — live data
HTTP_TIMEOUT          = int(os.getenv("HTTP_TIMEOUT_SECONDS","20"))
DATA_GOV_API_KEY      = os.getenv("DATA_GOV_API_KEY",       "")         # optional

DATA_URL = f"{CKAN_ACTION_BASE}/datastore_search"

# ── In-process caches ─────────────────────────────────────────────────────────
_info_cache:  dict = {"rows": None,      "ts": 0.0}
_avail_cache: dict = {"data": None,      "ts": 0.0, "timestamp": ""}


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
        row["longitude_translated"] = safe_float(row.get("longitude"))
        row["latitude_translated"]  = safe_float(row.get("latitude"))

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

def fetch_availability() -> dict:
    """
    Returns a dict keyed by carpark_number (upper-cased) whose value is a
    dict of lot_type → {lots_available, total_lots}.

    Example:
        {
          "HDB001": {"C": {"lots_available": 45, "total_lots": 100}, ...},
          ...
        }
    """
    r = requests.get(
        AVAILABILITY_URL,
        headers=_api_headers(),
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()

    items = payload.get("items", [])
    if not items:
        return {}

    # The API returns a list with one element (the latest snapshot)
    snapshot   = items[0]
    timestamp  = snapshot.get("timestamp", "")
    carpark_data = snapshot.get("carpark_data", [])

    result: dict = {}
    for entry in carpark_data:
        cp_no = entry.get("carpark_number", "").strip().upper()
        if not cp_no:
            continue
        lot_type = entry.get("lot_type", "?")
        result.setdefault(cp_no, {})[lot_type] = {
            "lots_available": int(entry.get("lots_available", 0)),
            "total_lots":     int(entry.get("total_lots",     0)),
        }

    return result, timestamp


def get_availability() -> tuple[dict, str]:
    """Return (availability_dict, snapshot_timestamp), refreshing if stale."""
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

LOT_TYPE_LABELS = {"C": "Cars", "H": "Heavy", "Y": "Motorcycles", "S": "Motorcycles (sidecar)"}

def summarise_availability(cp_avail: dict | None) -> dict:
    """
    Given the per-lot-type dict for one carpark, return a flat summary dict
    suitable for JSON serialisation and table display.

    Keys returned:
        avail_cars, total_cars,
        avail_heavy, total_heavy,
        avail_moto, total_moto,
        avail_total, total_lots,
        pct_available          (0-100, rounded to 1 dp; None if no data)
    """
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

    ca, tc = _get("C")
    ha, th = _get("H")
    # Y and S are both motorcycle types — sum them
    ya, ty = _get("Y")
    sa, ts_ = _get("S")

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
    """
    JSON endpoint polled by the frontend every 60 s.

    Returns:
        {
          "timestamp": "2025-...",
          "carparks": {
            "HDB001": {
              "avail_cars": 45, "total_cars": 100,
              "avail_heavy": null, "total_heavy": null,
              "avail_moto": 12, "total_moto": 50,
              "avail_total": 57, "total_lots": 150,
              "pct_available": 38.0
            },
            ...
          }
        }
    """
    avail, ts = get_availability()
    carparks = {cp: summarise_availability(lots) for cp, lots in avail.items()}
    return jsonify({"timestamp": ts, "carparks": carparks})


if __name__ == "__main__":
    app.run(debug=True)
