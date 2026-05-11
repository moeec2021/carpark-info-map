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
