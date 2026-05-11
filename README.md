# Carpark Table App (Flask) – Render.com Ready

A tiny Flask web app that pulls a **data.gov.sg** dataset via the CKAN Action API and renders the records in a sortable/searchable table.

This repo is designed to be deployed directly on **Render.com**.

## What it does
- Resolves a dataset/package ID to a datastore **resource_id** (via `package_show`).
- Downloads records from `datastore_search` with pagination.
- Caches results in-memory to reduce calls to data.gov.sg.
- Displays data in a browser table (DataTables for sorting/paging).
- Provides a `/download.csv` endpoint.

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DATASET_ID=d_23f946fa557947f93a8043bbef41dd09
python app.py
