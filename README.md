# Singapore Carpark Map

This is a Flask-based web application that visualises Singapore carpark data from **data.gov.sg** in:

- an interactive **table** (searchable, pageable, sortable), and
- an interactive **map** (MapLibre GL with OneMap raster tiles),

with tight **map ↔ table synchronisation**.

The app is designed to be:
- stored in **GitHub**, and
- built and served on **Render.com** (Python 3.11).

---

## Features

### Data
- Source: **data.gov.sg (CKAN API)**  
  Resource ID: `d_23f946fa557947f93a8043bbef41dd09`
- Fetches all records via `datastore_search` with pagination
- In-memory caching with TTL (configurable)

### Table
- Uses **DataTables**
- Default: 10 rows per page (10 / 25 / 50 / 100 supported)
- Client-side **search** (single search bar)
- All dataset columns shown
- Column headers:
  - Title Case
  - No underscores (e.g. `car_park_no` → `Car Park No`)
- Special columns:
  - `Longitude (Translated)`
  - `Latitude (Translated)`
- Column visibility toggles:
  - X Coord
  - Y Coord
  - Longitude (Translated)
  - Latitude (Translated)

### Map
- Uses **MapLibre GL JS**
- Basemap: **OneMap raster tiles (SLA)**  
  `https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png`
- No OneMap iframe
- No OneMap JS SDK
- Fully compatible with Render.com

### Map ↔ Table Sync (Improvements 1–6)
1. **Numbered markers (1–10)** for the first 10 rows on the current table page
2. Clicking a marker:
   - highlights the corresponding table row
   - pans/zooms the map
3. Clicking a table row pans/zooms the map
4. Markers update automatically when:
   - paging
   - sorting
   - searching
5. “Geocoded” indicator:
   - ✅ if valid translated coordinates exist
   - ⚠️ otherwise (row is not plotted)
6. Footer explains:
   - basemap source
   - coordinate conversion method

### Coordinate Conversion
- Input: **SVY21** (`x_coord`, `y_coord`)
- Output: **WGS84** (`longitude_translated`, `latitude_translated`)
- Conversion done **server-side in Python**
- No external GIS libraries (no `pyproj`, no `pandas`)

---

## Repository Structure

``
