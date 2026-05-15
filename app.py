import requests
from flask import Flask, render_template

app = Flask(__name__)

DATA_URL = "https://data.gov.sg/api/action/datastore_search"
RESOURCE_ID = "d_23f946fa557947f93a8043bbef41dd09"


def safe_float(v):
    try:
        return float(v)
    except:
        return None


def fetch_data():
    try:
        r = requests.get(DATA_URL, params={
            "resource_id": RESOURCE_ID,
            "limit": 2000
        }, timeout=20)

        r.raise_for_status()
        rows = r.json()["result"]["records"]

        for row in rows:
            row["longitude_translated"] = safe_float(row.get("longitude"))
            row["latitude_translated"] = safe_float(row.get("latitude"))

        return rows

    except Exception:
        return []


@app.route("/")
def index():
    rows = fetch_data()

    columns = list(rows[0].keys()) if rows else []

    return render_template(
        "index.html",
        app_title="Singapore Carpark Map",
        rows=rows,
        column_keys=columns,
        lon_t_key="longitude_translated",
        lat_t_key="latitude_translated",
        map_center=[103.8198, 1.3521]
    )


if __name__ == "__main__":
    app.run(debug=True)
