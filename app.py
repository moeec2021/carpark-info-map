import os
import math
import requests
from datetime import datetime, timezone
from flask import Flask, render_template

app = Flask(__name__)

RESOURCE_ID = os.getenv(
    "RESOURCE_ID",
    "d_23f946fa557947f93a8043bbef41dd09"
)
CKAN_API = "https://data.gov.sg/api/action/datastore_search"
FETCH_LIMIT = 5000

LON_T = "longitude_translated"
LAT_T = "latitude_translated"


# --- SVY21 → WGS84 ---
def svy21_to_wgs84(E, N):
    a = 6378137
    f = 1 / 298.257223563
    e2 = 2*f - f*f
    lat0 = math.radians(1.3666666667)
    lon0 = math.radians(103.8333333333)
    FE, FN = 28001.642, 38744.572

    x = E - FE
    y = N - FN
    M = y
    mu = M / (a * (1 - e2/4))

    phi = mu
    N1 = a / math.sqrt(1 - e2 * math.sin(phi)**2)
    D = x / N1

    lat = phi
    lon = lon0 + D / math.cos(phi)

    return math.degrees(lon), math.degrees(lat)


@app.route("/")
def index():
    r = requests.get(
        CKAN_API,
        params={"resource_id": RESOURCE_ID, "limit": FETCH_LIMIT},
        timeout=20,
    ).json()["result"]

    columns = [f["id"] for f in r["fields"] if not f["id"].startswith("_")]
    rows = r["records"]

    for rec in rows:
        try:
            x = float(rec.get("x_coord", ""))
            y = float(rec.get("y_coord", ""))
            lon, lat = svy21_to_wgs84(x, y)
            rec[LON_T] = f"{lon:.6f}"
            rec[LAT_T] = f"{lat:.6f}"
        except:
            rec[LON_T] = ""
            rec[LAT_T] = ""

    display_cols = (
        [c for c in columns if c not in ("x_coord", "y_coord")]
        + ["x_coord", "y_coord", LON_T, LAT_T]
    )

    pts = [
        (float(r[LON_T]), float(r[LAT_T]))
        for r in rows[:10]
        if r[LON_T] and r[LAT_T]
    ]
    map_center = (
        (sum(p[1] for p in pts)/len(pts), sum(p[0] for p in pts)/len(pts))
        if pts else (1.3521, 103.8198)
    )

    return render_template(
        "index.html",
        app_title="Singapore Carpark Map",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        resource_id=RESOURCE_ID,
        rows=rows,
        column_keys=display_cols,
        map_center=map_center,
        map_points=pts,
    )


if __name__ == "__main__":
    app.run()
