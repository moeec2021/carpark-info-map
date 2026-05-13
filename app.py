import os
import math
import requests
from flask import Flask, render_template

app = Flask(__name__)

APP_TITLE = "Singapore Carpark Map"
RESOURCE_ID = "d_23f946fa557947f93a8043bbef41dd09"
CKAN_URL = "https://data.gov.sg/api/action/datastore_search"

X_COL = "x_coord"
Y_COL = "y_coord"
LON_T = "longitude_translated"
LAT_T = "latitude_translated"


def svy21_to_wgs84(E, N):
    a = 6378137
    f = 1 / 298.257223563
    e2 = 2 * f - f * f
    lat0 = math.radians(1.3666666667)
    lon0 = math.radians(103.8333333333)
    FE, FN = 28001.642, 38744.572

    x = E - FE
    y = N - FN
    N1 = a / math.sqrt(1 - e2 * math.sin(lat0)**2)

    lon = lon0 + x / N1
    lat = lat0 + y / a

    return math.degrees(lon), math.degrees(lat)


@app.route("/")
def index():
    r = requests.get(
        CKAN_URL,
        params={"resource_id": RESOURCE_ID, "limit": 5000},
        timeout=20
    ).json()["result"]

    columns = [f["id"] for f in r["fields"] if not f["id"].startswith("_")]
    rows = r["records"]

    for rec in rows:
        try:
            x = float(rec.get(X_COL, ""))
            y = float(rec.get(Y_COL, ""))
            lon, lat = svy21_to_wgs84(x, y)
            rec[LON_T] = f"{lon:.6f}"
            rec[LAT_T] = f"{lat:.6f}"
        except:
            rec[LON_T] = ""
            rec[LAT_T] = ""

    columns = [c for c in columns if c not in (X_COL, Y_COL)] + \
              [X_COL, Y_COL, LON_T, LAT_T]

    pts = [
        [float(r[LON_T]), float(r[LAT_T])]
        for r in rows[:10]
        if r[LON_T] and r[LAT_T]
    ]

    center = pts[0] if pts else [103.8198, 1.3521]

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        resource_id=RESOURCE_ID,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        rows=rows,
        column_keys=columns,
        map_center=center,
        map_points=pts
    )


if __name__ == "__main__":
    app.run()
