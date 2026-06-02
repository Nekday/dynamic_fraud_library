# Fraud Taxonomy — Flask App

Browser GUI for the fraud taxonomy: browse types, view signals/selectors,
and run the two-lane staging review. Plain Flask + psycopg (raw SQL, all in `db.py`).

## Prerequisites

- PostgreSQL running (Postgres.app), with the schema + seed already loaded
  (001_schema.sql, 002_seed.sql, and optionally 003_seed_staging.sql).
- Python 3.10+

## Setup (macOS)

```bash
cd fraud_taxonomy
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
cd app
flask --app app run --debug
```

Open http://127.0.0.1:5000

## Database connection

By default the app connects to Postgres.app locally:

```
postgresql://localhost/fraud_taxonomy
```

To point elsewhere (e.g., AWS RDS later), set one environment variable — no code change:

```bash
export FT_DATABASE_URI='postgresql://USER:PASSWORD@HOST:5432/fraud_taxonomy'
```

## What each page does

- **Types** — the taxonomy spine. Full-text search + filter by AI-leverage tag.
- **Type detail** — tags by dimension, TTPs in HUMINT-phase order, detection
  signals (color-coded by class), selectors, fraudster/victim profiles, observations.
- **Signals** — every detection signal across all types; behavioral signals are the
  classifier-guideline bridge.
- **Selectors** — hard IOCs (IP, IMEI, MAC, wallet, mule account, gift-card code…).
- **Systems** — the external-system registry (HMA, TransUnion, STIX/TAXII, CISA AIS…).
- **Review** — two-lane human-in-the-loop staging: a **bulk** lane that trust-approves
  provenance-verified batches (hash/selector lists) and a **single** lane that reviews
  narrative entries one at a time. Nothing reaches the live tables unreviewed.

Each object shows its STIX equivalent inline (the naming bridge).

## Optional: load demo staging data

To see the review screen populated:

```bash
psql -d fraud_taxonomy -f ../db/003_seed_staging.sql
```

## Architecture note

`db.py` holds every SQL statement in plain text — nothing is hidden behind an ORM.
`app.py` is routing and view logic only. This separation keeps the SQL reviewable
and makes the data layer easy to test or swap.
