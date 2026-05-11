import os
import time
from typing import Any, Dict, List, Tuple

import requests
from flask import Flask, Response, render_template, request

APP_TITLE = os.getenv("APP_TITLE", "Singapore Carpark Info (Table View)")

# IMPORTANT:
# We do NOT call package_show (403 Forbidden on data.gov.sg for some dataset ids).
# We call datastore_search directly using RESOURCE_ID (which is what your python query does).
CKAN_ACTION_BASE = os.getenv("CKAN_ACTION_BASE", "https://data.gov.sg/api/action").rstrip("/")
RESOURCE_ID = os.getenv("RESOURCE_ID", "d_23f946fa557947f93a8043bbef41dd09").strip()

# Fetch controls
FETCH_LIMIT = int(os.getenv("FETCH_LIMIT", "5000"))        # per page
MAX_RECORDS = int(os.getenv("MAX_RECORDS", "20000"))       # safety cap
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", str(6 * 60 * 60)))  # 6 hours default

# Display controls
DISPLAY_MAX_ROWS = int(os.getenv("DISPLAY_MAX_ROWS", "2000"))

# HTTP controls
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))
USER_AGENT = os.getenv("USER_AGENT", "carpark-table-app/1.1")

app = Flask(__name__)

_cache: Dict[str, Any] = {
    "fetched_at": 0.0,
    "resource_id": RESOURCE_ID,
    "records": [],
    "fields": [],
    "error": None,
    "total": 0,
}


def _ckan_get(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{CKAN_ACTION_BASE}/{action}"
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SECONDS, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not data.get("success"):
        raise RuntimeError(f"CKAN action failed: {data}")
    return data


def fetch_all_records(resource_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """Fetch records from datastore_search with pagination via offset/limit."""
    records: List[Dict[str, Any]] = []
    fields: List[Dict[str, Any]] = []
    offset = 0
    total = 0

    while True:
        limit = min(FETCH_LIMIT, MAX_RECORDS - len(records))
        if limit <= 0:
            break

        page = _ckan_get(
            "datastore_search",
            {
                "resource_id": resource_id,
                "limit": limit,
                "offset": offset,
            },
        ).get("result", {})

        if not fields:
            fields = page.get("fields") or []

        page_records = page.get("records") or []
        total = int(page.get("total") or total or 0)

        if not page_records:
            break

        records.extend(page_records)
        offset += len(page_records)

        if len(records) >= MAX_RECORDS:
            break
        if total > 0 and offset >= total:
            break

    return records, fields, total


def filter_records_contains(records: List[Dict[str, Any]], q: str) -> List[Dict[str, Any]]:
    """Simple contains search across all fields (server-side)."""
    if not q:
        return records
    q_lower = q.lower()
    out = []
    for r in records:
        for v in r.values():
            if v is None:
                continue
            if q_lower in str(v).lower():
                out.append(r)
                break
    return out


def get_data(force: bool = False) -> Dict[str, Any]:
    now = time.time()

    if (not force) and _cache["records"] and (now - _cache["fetched_at"] < CACHE_TTL_SECONDS):
        return _cache

    try:
        records, fields, total = fetch_all_records(RESOURCE_ID)

        # Determine display column order from CKAN fields, fallback to record keys
        if fields:
            col_order = [f.get("id") for f in fields if f.get("id")]
        else:
            col_order = list(records[0].keys()) if records else []

        # Remove internal keys if present
        col_order = [c for c in col_order if c not in ("_id", "_full_text")]

        _cache.update(
            {
                "fetched_at": now,
                "resource_id": RESOURCE_ID,
                "records": records,
                "fields": col_order,
                "error": None,
                "total": total,
            }
        )
    except Exception as e:
        _cache.update(
            {
                "fetched_at": now,
                "resource_id": RESOURCE_ID,
                "error": str(e),
                "records": [],
                "fields": [],
                "total": 0,
            }
        )

    return _cache


@app.get("/")
def index():
    q = request.args.get("q", "").strip()
    force = request.args.get("refresh") == "1"

    data = get_data(force=force)
    error = data.get("error")

    records = data.get("records", [])
    cols = data.get("fields", [])

    if q and records:
        records = filter_records_contains(records, q)

    # Cap display size for browser performance
    records_to_show = records[:DISPLAY_MAX_ROWS]

    return render_template(
        "index.html",
        title=APP_TITLE,
        resource_id=data.get("resource_id"),
        fetched_at=data.get("fetched_at"),
        total=data.get("total"),
        error=error,
        q=q,
        cols=cols,
        rows=records_to_show,
        shown=len(records_to_show),
        filtered=len(records),
        display_max=DISPLAY_MAX_ROWS,
    )


@app.get("/download.csv")
def download_csv():
    q = request.args.get("q", "").strip()
    data = get_data(force=False)
    error = data.get("error")
    if error:
        return Response(f"Error: {error}\n", status=500, mimetype="text/plain")

    records = data.get("records", [])
    cols = data.get("fields", [])

    if q and records:
        records = filter_records_contains(records, q)

    def gen():
        import csv
        from io import StringIO

        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for r in records:
            writer.writerow(r)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return Response(
        gen(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=carpark_info.csv"},
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
