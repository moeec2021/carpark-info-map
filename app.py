import os
import time
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify, url_for


def env_str(name, default):
    v = os.getenv(name)
    return default if not v else v


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


APP_TITLE = env_str("APP_TITLE", "Singapore Carpark Info (Table View)")
RESOURCE_ID = env_str("RESOURCE_ID", "d_23f946fa557947f93a8043bbef41dd09")
CKAN_ACTION_BASE = env_str("CKAN_ACTION_BASE", "https://data.gov.sg/api/action")
FETCH_LIMIT = env_int("FETCH_LIMIT", 5000)
MAX_RECORDS = env_int("MAX_RECORDS", 20000)
CACHE_TTL_SECONDS = env_int("CACHE_TTL_SECONDS", 21600)
DISPLAY_MAX_ROWS = env_int("DISPLAY_MAX_ROWS", 2000)
HTTP_TIMEOUT_SECONDS = env_int("HTTP_TIMEOUT_SECONDS", 20)

LAT_COL = "latitude"
LON_COL = "longitude"

app = Flask(__name__)

_cache = {}
_cache_lock = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_all_records():
    records = []
    offset = 0
    total = None

    while True:
        resp = requests.get(
            f"{CKAN_ACTION_BASE}/datastore_search",
            params={
                "resource_id": RESOURCE_ID,
                "limit": FETCH_LIMIT,
                "offset": offset,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()["result"]

        if total is None:
            total = data["total"]

        batch = data["records"]
        records.extend(batch)
        offset += len(batch)

        if offset >= total or len(records) >= MAX_RECORDS:
            break

    return records[:MAX_RECORDS], total


def get_cached_data(force=False):
    with _cache_lock:
        if not force and _cache.get("expires_at", 0) > time.time():
            return _cache

