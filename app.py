from flask import Flask, render_template
from datetime import datetime, timezone

app = Flask(__name__)

@app.route("/")
def index():
    # Sample data structure – replace with your real data source
    rows = [
        {"name": "Carpark A", "latitude": 1.301063, "longitude": 103.854118},
        {"name": "Carpark B", "latitude": 1.321004, "longitude": 103.885061},
        {"name": "Carpark C", "latitude": 1.328283, "longitude": 103.844620},
        {"name": "Carpark D", "latitude": 1.369091, "longitude": 103.834985},
        {"name": "Carpark E", "latitude": 1.366120, "longitude": 103.846636},
        {"name": "Carpark F", "latitude": 1.372439, "longitude": 103.850296},
        {"name": "Carpark G", "latitude": 1.383599, "longitude": 103.848368},
        {"name": "Carpark H", "latitude": 1.368741, "longitude": 103.840301},
        {"name": "Carpark I", "latitude": 1.370350, "longitude": 103.835718},
        {"name": "Carpark J", "latitude": 1.365540, "longitude": 103.844619},
    ]

    # Compute map center from first 10 rows
    avg_lat = sum(r["latitude"] for r in rows[:10]) / len(rows[:10])
    avg_lon = sum(r["longitude"] for r in rows[:10]) / len(rows[:10])

    return render_template(
        "index.html",
        app_title="Carpark Map (OneMap + MapLibre)",
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        total_ckan=len(rows),
        rows=rows,
        columns=["name", "latitude", "longitude"],
        map_center=(avg_lat, avg_lon)
    )

if __name__ == "__main__":
    app.run(debug=True)
