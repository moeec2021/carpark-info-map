import os
import time
import threading
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

LAT_CANDIDATES = ["latitude", "lat", "Latitude", "LAT"]
LON_CANDIDATES = ["longitude", "lon", "lng", "Longitude", "LON"]

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
            total = result["total"]

        batch = result["records"]
        records.extend(batch)
        offset += len(batch)

        if offset >= total or len(records) >= MAX_RECORDS:
            break

    return records[:MAX_RECORDS], total


def find_coord_columns(columns):
    lat_col = next((c for c in columns if c in LAT_CANDIDATES), None)
    lon_col = next((c for c in columns if c in LON_CANDIDATES), None)
    return lat_col, lon_col


def get_data(refresh=False):
    with _cache_lock:
        if not refresh and _cache.get("expires", 0) > time.time():
            return _cache

    records, total = fetch_all()
    columns = [k for k in records[0] if not k.startswith("_")] if records else []
    lat_col, lon_col = find_coord_columns(columns)

    with _cache_lock:
        _cache.update({
            "records": records,
            "columns": columns,
            "lat_col": lat_col,
            "lon_col": lon_col,
            "total": total,
            "fetched": now_iso(),
            "expires": time.time() + CACHE_TTL_SECONDS
        })

    return _cache


