from flask import Flask, render_template
import requests

app = Flask(__name__)

DATA_URL = "https://data.gov.sg/api/action/datastore_search?resource_id=23f946fa-5579-47f9-3a80-43bbef41dd09"

@app.route("/")
def index():
    response = requests.get(DATA_URL)
    data = response.json()
    carparks = data["result"]["records"]
    return render_template("index.html", carparks=carparks)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
