You are a senior full-stack engineer. Build a complete GitHub repository for a Python Flask web app that is built and served on Render.com. The app displays Singapore carpark information from data.gov.sg in a DataTables table and a MapLibre map using OneMap raster tiles, with full map↔table synchronisation and robust UI controls. Output full file contents for every file listed under “FILES TO OUTPUT”.

ABSOLUTE QUALITY COMMITMENTS (MUST FOLLOW)
1) Do NOT remove or regress features when fixing bugs. Preserve ALL features listed below.
2) Always output FULL implementation files, not partial snippets.
3) Always do a self-check pass before outputting code:
   - Ensure MapLibre is included via proper <link> and <script> tags (never bare URLs in HTML).
   - Ensure templates are raw HTML (never HTML-escaped: no &lt;html&gt; or &lt;script&gt;).
   - Ensure #map has explicit CSS height.
   - Ensure marker creation happens only inside map.on('load').
   - Ensure column toggles do not break map logic (must not read coordinates from DOM cells).
   - Ensure night-parking detection is column-agnostic and cannot crash if the column is missing.
   - Ensure table header and body are generated from the SAME ordered key list (no misalignment).
4) Defensive coding: never allow one UI feature to break the whole page. Catch errors and log to console with clear messages.

DATA REQUIREMENTS
A) Use ONLY CKAN datastore_search endpoint. Do NOT use package_show.
   - CKAN action base: https://data.gov.sg/api/action
   - resource_id must be exactly: d_23f946fa557947f93a8043bbef41dd09
   - fetch all records via offset/limit pagination, with env defaults below.
B) Exclude internal keys from display: keys starting with "_" plus _id and _full_text.
C) Ensure these dataset columns appear when present (the app shows ALL columns, but these are important):
   car_park_no, address, x_coord, y_coord, car_park_type, type_of_parking_system,
   short_term_parking, free_parking, night_parking, car_park_decks, gantry_height, car_park_basement.
D) Convert SVY21 x_coord/y_coord to WGS84 lon/lat in Python (NO pandas, NO pyproj).
   - Add two computed fields per record:
     longitude_translated
     latitude_translated
   - Format as strings with 6 decimal places.
E) Display column order:
   - Show all dataset columns
   - Move x_coord and y_coord to the far right
   - Append Longitude (Translated) and Latitude (Translated) as the last two columns
F) Column header display:
   - Title Case, underscores replaced with spaces (e.g., car_park_no → Car Park No)
   - Special labels: Longitude (Translated), Latitude (Translated)

MAP REQUIREMENTS
1) Map engine: MapLibre GL JS via CDN.
2) Basemap: OneMap raster tiles (NOT OneMap iframe; NOT OneMap JS SDK).
   - Tile URL: https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png
3) Map must render reliably on Render.com:
   - Proper <link rel="stylesheet"> for MapLibre CSS
   - Proper <script src="..."></script> for MapLibre JS
   - Explicit #map height in CSS
   - Markers added only inside map.on('load')

TABLE + UX REQUIREMENTS (FEATURES THAT MUST BE INCLUDED)
Improvements 1–6 + search + toggles must all be included:

(SEARCH)
- Provide a single search bar (client-side) that searches the DataTables content.
- Do not show the default DataTables search box; use dom: 'lrtip' and your own input field.
- Searching must update the map markers to match current page.

(TOGGLES)
- Provide column visibility toggles for:
  x_coord, y_coord, Longitude (Translated), Latitude (Translated)
- Toggles MUST work and MUST NOT affect marker plotting incorrectly.
- Implementation requirement: marker plotting MUST read coordinates from DataTables row data (table.row(...).data()), never from DOM td indices (which shift when columns hide).

(1) Numbered markers
- Plot ALL locations on the current DataTables page (not limited to 10).
- Markers are numbered 1..N for the page.
- A “#” column in the table must show the same numbers.

(2) Map↔table sync
- Clicking a marker highlights the corresponding table row and pans/zooms the map.
- Clicking a table row pans/zooms the map and highlights the row.

(3) Auto-update markers
- On DataTables draw event (paging, sorting, searching), regenerate markers to match the visible page rows.

(4) Column visibility toggles
- Already stated above; must not break markers.

(5) Coordinate validation
- “Geocoded” column shows ✅ if translated lon/lat exist and parse; else ⚠️ and row is not plotted.

(6) Footer
- Footer must state:
  - Base map: OneMap raster tiles (Singapore Land Authority)
  - Coordinate conversion: SVY21 → WGS84 computed server-side

Night-parking marker colour feature:
- Use BLUE locator icons for carparks with night parking, RED otherwise.
- Night-parking detection must be column-agnostic:
  - Identify the night parking column by scanning header keys/text for tokens containing both “night” and “parking” (case-insensitive, underscore/space agnostic).
  - If no night parking column exists, default all markers to red.
  - Parse “night parking available” as true if value includes yes/y/true/available (case-insensitive).

BACKEND REQUIREMENTS
- Flask routes:
  - GET / : render page with table + map + features
  - GET /healthz : returns {"ok": true}
  - GET /download.csv : streams CSV (honour q filter if provided; same column order as UI)
- Caching:
  - In-memory cache with TTL
  - refresh=1 bypasses cache
- Server-side filter:
  - Support optional query param q for server-side contains filter across all fields (applied before render).
  - This is separate from client-side search; keep both and label clearly:
    - Server-side filter input box (q) and submit button
    - Client-side DataTables search input
  - Ensure UI does not show duplicate search boxes from DataTables.

ENV VARS (defaults)
- APP_TITLE = Singapore Carpark Map
- RESOURCE_ID = d_23f946fa557947f93a8043bbef41dd09
- CKAN_ACTION_BASE = https://data.gov.sg/api/action
- FETCH_LIMIT = 5000
- MAX_RECORDS = 20000
- CACHE_TTL_SECONDS = 21600
- HTTP_TIMEOUT_SECONDS = 20

RENDER DEPLOYMENT
- Provide render.yaml:
  - type: web
  - env: python
  - pythonVersion: 3.11.9
  - buildCommand: pip install -r requirements.txt
  - startCommand: gunicorn app:app
- Provide .python-version with 3.11.9
- Provide requirements.txt with:
  Flask==3.0.3
  gunicorn==22.0.0
  requests==2.32.3

FILES TO OUTPUT (FULL CONTENTS)
- app.py
- templates/index.html
- static/style.css
- requirements.txt
- render.yaml
- .python-version
- README.md (local run + Render deploy + troubleshooting + feature list)
- .gitignore

FINAL SELF-CHECK (MUST DO BEFORE PRINTING OUTPUT)
- templates/index.html contains valid <link> and <script> tags for MapLibre and DataTables (no bare URLs).
- templates/index.html is not HTML-escaped.
- #map has explicit height in static/style.css.
- Markers are created only after map.on('load').
- Marker plotting reads lon/lat from DataTables row().data() not from DOM td indexing.
- Column toggles do not break marker plotting.
- Night-parking detection cannot crash and is column-agnostic.
- Table header/rows aligned and derived from same key list.
- No feature removal: search + toggles + sync + coloured markers all included.

Now generate the full contents of every file listed in FILES TO OUTPUT.
For each file, print:
FILE: <path>
<full file contents>
