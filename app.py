import os
import time
import requests
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# ------------------------
# CONFIG
# ------------------------
AVAIL_TTL = 60

AVAIL_CACHE = {
    "expires": 0,
    "timestamp": "",
    "data": {}
}

# ------------------------
# NORMALIZATION (CRITICAL)
# ------------------------
def normalize_carpark_no(v):
    if not v:
        return ""
    return str(v).upper().replace(" ", "").strip()

# ------------------------
# AVAILABILITY FETCH
# ------------------------
def fetch_availability():
    now = time.time()

    if now < AVAIL_CACHE["expires"]:
        return AVAIL_CACHE

    amap = {}
    ts = ""

    try:
        r = requests.get(
            "https://api.data.gov.sg/v1/transport/carpark-availability",
            timeout=10
        )
        r.raise_for_status()
        payload = r.json()

        items = payload.get("items", [])
        if items:
            first = items[0]
            ts = first.get("timestamp", "")

            for entry in first.get("carpark_data", []):
                raw_id = entry.get("carpark_number") or ""
                key = normalize_carpark_no(raw_id)

                if not key:
                    continue

                amap[key] = {}

                for item in entry.get("carpark_info", []):
                    lt = item.get("lot_type")
                    amap[key][lt] = {
                        "available": item.get("lots_available"),
                        "total": item.get("total_lots")
                    }

    except Exception:
        amap = {}
        ts = ""

    AVAIL_CACHE.update({
        "expires": now + AVAIL_TTL,
        "timestamp": ts,
        "data": amap
    })

    return AVAIL_CACHE


# ------------------------
# ROUTES
# ------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        app_title="Singapore Carpark Map",
        map_center=[103.8198, 1.3521],
        avail_ttl=AVAIL_TTL
    )


@app.route("/availability.json")
def availability():
    return jsonify(fetch_availability())


@app.route("/healthz")
def healthz():
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
