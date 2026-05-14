# Carpark Info Table App (Flask) – Render.com Ready

A small Flask web app that reads carpark information from **data.gov.sg** using the **datastore_search** endpoint and shows it in a sortable/searchable table.

## Why this version works on Render
Some data.gov.sg CKAN catalog endpoints (e.g., `package_show`) can return **403 Forbidden** in hosted environments.
This app avoids that entirely by calling `datastore_search` directly with `RESOURCE_ID`, matching the working Python query you provided.

## Local run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export RESOURCE_ID=d_23f946fa557947f93a8043bbef41dd09
python app.py



# Prompt for co-pilot
You are a senior full-stack engineer. Generate a complete GitHub repository for a Python Flask web app deployable on Render.com that displays Singapore carpark information in a DataTable and an interactive MapLibre map using OneMap raster tiles. The output must be a full, stable implementation (NOT a minimal demo).

NON-NEGOTIABLE REQUIREMENTS (must pass)
1) Data source:
   - Use ONLY CKAN datastore_search endpoint. Do NOT call package_show.
   - resource_id MUST be: d_23f946fa557947f93a8043bbef41dd09
   - CKAN action base: https://data.gov.sg/api/action
   - Fetch all records using offset/limit pagination (limit default 5000) until done or MAX_RECORDS cap.
2) Map:
   - Must work reliably on Render.com.
   - Use MapLibre GL JS via CDN, included using correct HTML tags:
     <link rel="stylesheet" href="...maplibre-gl.css">
     <script src="...maplibre-gl.js"></script>
   - DO NOT paste bare URLs for CSS/JS in the HTML. That MUST NOT happen.
   - Use OneMap raster tiles (no OneMap iframe and no OneMap JS SDK):
     tiles: https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png
   - Use inline style object in MapLibre (do NOT use OneMap JSON style URLs).
   - Ensure the map container has explicit CSS height (#map height >= 480px).
   - Add markers ONLY inside map.on('load', ...) to avoid timing/race issues.
3) Templates MUST be raw HTML and must NOT be HTML-escaped:
   - No &lt;html&gt; or &lt;script&gt; in templates/index.html.
4) Table correctness:
   - Header and body MUST be generated from the SAME ordered list of column keys to avoid misalignment.
   - Show ALL dataset columns (excluding keys that start with "_" and internal keys like _id, _full_text).
   - Move x_coord and y_coord to the far right side of the table.
   - Append two computed columns as the last two:
     longitude_translated
     latitude_translated
   - Column titles shown in the browser must be Title Case, with underscores replaced by spaces.
     Example: "car_park_no" -> "Car Park No"
     Special labels must be "Longitude (Translated)" and "Latitude (Translated)".
5) Coordinate conversion:
   - Dataset uses SVY21 coordinates x_coord/y_coord (Easting/Northing).
   - Convert SVY21 (EPSG:3414) -> WGS84 (EPSG:4326) in Python with NO external libs (no pandas, no pyproj).
   - Use SVY21 projection parameters:
     Central Meridian: 103°50'00"E
     Latitude of Origin: 1°22'00"N
     False Easting: 28001.642
     False Northing: 38744.572
     Scale factor at CM: 1.000
     WGS84 ellipsoid: a=6378137, inv_f=298.257223563
   - Store results in each record as:
     longitude_translated (decimal degrees, 6 dp string)
     latitude_translated (decimal degrees, 6 dp string)
6) Improvements 1–6 MUST be implemented:
   1. Numbered markers 1–10 matching a "#" column.
   2. Map↔table sync:
      - clicking a marker highlights the corresponding row and pans the map
      - clicking a row pans the map
   3. Auto-update markers when DataTables paging changes (hook DataTables draw event).
   4. Column visibility toggles for: x_coord, y_coord, Longitude (Translated), Latitude (Translated).
   5. "Geocoded" indicator column:
      - ✅ if translated lon/lat present else ⚠️
      - invalid rows are not plotted on map
   6. Footer text explaining base map and conversion method (source/methodology).
7) Routes:
   - GET / : main page with server-side contains filter q=..., refresh=1 bypass cache
   - GET /download.csv : returns CSV with the same column order as the table (apply q filter if present)
   - GET /healthz : returns {"ok": true}
8) Rendering constraints:
   - The page must never print JavaScript source text onto the page.
   - The page must never print MapLibre CSS/JS URLs as plain text.
   - If JS fails, it should still render the table HTML; but map must work when JS is loaded correctly.
9) Render deployment:
   - Include render.yaml with pythonVersion 3.11.9, buildCommand pip install -r requirements.txt, startCommand gunicorn app:app
   - Include .python-version = 3.11.9
   - requirements.txt must include only: Flask, gunicorn, requests (pinned or compatible).
   - Provide README.md with local run and Render steps.

FILES TO OUTPUT (full contents, no placeholders)
- app.py
- requirements.txt
- render.yaml
- .python-version
- README.md
- .gitignore
- templates/index.html
- static/style.css

IMPLEMENTATION NOTES (must follow)
- Use in-memory cache dict with expires_at TTL; refresh=1 bypasses cache.
- Use requests with timeout env var.
- DataTables should default to 10 rows per page and allow 10/25/50/100.
- Hide DataTables built-in search box to avoid a second search field (server-side filter remains).
- Use data-colkey attributes in table header cells so toggles and column indexing are stable.

OUTPUT FORMAT
For each file, output:
1) A filename line: "FILE: <path>"
2) Then the full file content.
Do NOT wrap the file contents in HTML escaping.
Do NOT output bare URLs outside code blocks; all code files must contain correct tags.

Before finishing, self-check:
- Does templates/index.html contain correct <link> and <script> tags for MapLibre?
- Does #map have an explicit height in CSS?
- Are markers added inside map.on('load')?
- Are header and body generated from same column_keys list?
- Do x_coord/y_coord show values?
- Are translated lon/lat displayed and used for markers?
- Are numbered markers and sync implemented?
- Does nothing print JS code to the page?

Now generate the full repository files.
