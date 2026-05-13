import os
import time
import math
import requests
from datetime import datetime, timezone
from flask import Flask, render_template

app = Flask(__name__)

# -------------------------------
# Configuration
# -------------------------------
RESOURCE_ID = os.getenv(
    "RESOURCE_ID",
    "d_23f946fa557947f93a8043bbef41dd09"
)
CKAN_BASE = "https://data.gov.sg/api/action"
FETCH_LIMIT = 5000
CACHE_TTL = 21600  # 6 hours

LON_T = "longitude_translated"
LAT_T = "latitude_translated"

cache = {
    "expires": 0,
    "records": [],
    "columns": [],
    "fetched_at": "",
    "total": 0
}

# -------------------------------
# SVY21 → WGS84 conversion
# -------------------------------
def svy21_to_wgs84(E, N):
    a = 6378137
    f = 1 / 298.257223563
    b = a * (1 - f)
    e2 = (a * a - b * b) / (a * a)
    lat0 = math.radians(1.3666666666666667)
    lon0 = math.radians(103.83333333333333)
    FE, FN = 28001.642, 38744.572

    x = E - FE
    y = N - FN

    M = y
    mu = M / (a * (1 - e2 / 4 - 3 * e2**2 / 64))

    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = mu \
        + (3*e1/2)*math.sin(2*mu) \
        + (21*e1**2/16)*math.sin(4*mu)

    C1 = e2 * math.cos(phi1)**2
    T1 = math.tan(phi1)**2
    N1 = a / math.sqrt(1 - e2 * math.sin(phi1)**2)
    R1 = a * (1 - e2) / (1 - e2 * math.sin(phi1)**2)**1.5
    D = x / N1

    lat = phi1 - (N1*math.tan(phi1)/R1) * (D**2/2)
    lon = lon0 + D / math.cos(phi1)

    return math.degrees(lon), math.degrees(lat)

# -------------------------------
# Data loading
# -------------------------------
def fetch_data():
    global cache
    if time.time() < cache["expires"]:
        return

    url = f"{CKAN_BASE}/datastore_search"
    offset = 0
    records = []
    columns = []

    while True:
        r = requests.get(url, params={
            "resource_id": RESOURCE_ID,
            "limit": FETCH_LIMIT,
            "offset": offset
        }, timeout=20)
        j = r.json()["result"]

        if not columns:
            columns = [f["id"] for f in j["fields"] if not f["id"].startswith("_")]

        batch = j["records"]
        records.extend(batch)
        offset += len(batch)
        if len(batch) < FETCH_LIMIT:
            break

    # add translated lat/lon
    for rec in records:
        try:
            x = float(rec.get("x_coord", ""))
            y = float(rec.get("y_coord", ""))
            lon, lat = svy21_to_wgs84(x, y)
            rec[LON_T] = f"{lon:.6f}"
            rec[LAT_T] = f"{lat:.6f}"
        except:
            rec[LON_T] = ""
            rec[LAT_T] = ""

    # reorder columns
    ordered = [c for c in columns if c not in ("x_coord", "y_coord")]
    ordered += ["x_coord", "y_coord", LON_T, LAT_T]

    cache.update({
        "records": records,
        "columns": ordered,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total": len(records),
        "expires": time.time() + CACHE_TTL
    })

# -------------------------------
# Route
# -------------------------------
@app.route("/")
def index():
    fetch_data()

    pts = [
        (float(r[LON_T]), float(r[LAT_T]))
        for r in cache["records"][:10]
        if r[LON_T] and r[LAT_T]
    ]

    if pts:
        center = (
            sum(p[1] for p in pts) / len(pts),
            sum(p[0] for p in pts) / len(pts)
        )
    else:
        center = (1.3521, 103.8198)

    return render_template(
        "index.html",
        app_title="Singapore Carpark Map (RabbitDeploy)",
        resource_id=RESOURCE_ID,
        fetched_at=cache["fetched_at"],
        total_ckan=cache["total"],
        rows=cache["records"],
        column_keys=cache["columns"],
        map_center=center,
    )
