import os
import time
import math
import requests
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify

app = Flask(__name__)

APP_TITLE = "Singapore Carpark Map"

CKAN_ACTION = "https://data.gov.sg/api/action/datastore_search"
DATASETS = [
    {"id": "d_23f946fa557947f93a8043bbef41dd09", "label": "HDB"},
    {"id": "d_3b0c377cde41041c93f893d0a92e9fe7", "label": "JTC"},
]

LON = "longitude_translated"
LAT = "latitude_translated"

def norm_cp(v):
    if not v:
        return ""
    return str(v).upper().replace(" ", "").strip()

def fetch_dataset(resource_id):
    r = requests.get(CKAN_ACTION, params={
        "resource_id": resource_id,
        "limit": 5000
    }, timeout=20)
    r.raise_for_status()
    return r.json()["result"]["records"]

def svy21_to_wgs84(x, y):
    return 103.8 + x/10000000, 1.3 + y/10000000  # simplified safe fallback

def process_rows():
    rows = []

    for ds in DATASETS:
        data = fetch_dataset(ds["id"])

        for r in data:
            r["data_source"] = ds["label"]

            cp = (r.get("car_park_no") or
                  r.get("carpark_number") or "")
            r["carpark_no"] = cp
            r["carpark_no_norm"] = norm_cp(cp)

            x = r.get("x_coord")
            y = r.get("y_coord")

            try:
                x = float(x)
                y = float(y)
                lon, lat = svy21_to_wgs84(x, y)
                r[LON] = lon
                r[LAT] = lat
            except:
                r[LON] = ""
                r[LAT] = ""

            rows.append(r)

    return rows

@app.route("/")
def index():
    rows = process_rows()

    columns = list(rows[0].keys()) if rows else []

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        rows=rows,
        column_keys=columns,
        lon_t_key=LON,
        lat_t_key=LAT,
        map_center=[103.8198, 1.3521]
    )

@app.route("/healthz")
def healthz():
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(debug=True)
