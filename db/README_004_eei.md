# Migration 004 — EEI Extraction Layer

Adds the "Essential Elements of Information" workflow to the taxonomy.

## What it adds

**On `observation`:**
- `captured_text` — our own stored copy of the case article (for highlighting + archival)
- `captured_at` — when we fetched it
- `staging_id` — links an observation back to the staging item it was promoted from

**New table `eei_candidate`** — extracted/proposed EEIs awaiting human review:
- `classifier_type` — email | phone | url | amount | behavioral | ttp (extensible)
- `eei_class` — selector | behavioral | ttp (determines promotion target)
- `matched_value` / `highlight_text` — the extracted value and the span to highlight
- `start_offset` / `end_offset` — character offsets into `captured_text` for GUI highlighting
- `origin` — regex | human | ai (who proposed it)
- `status` — pending | approved | rejected
- `note`, `confidence` — reviewer detail used when promoting a behavioral EEI to a signal
- `promoted_selector_id` / `promoted_signal_id` — which live row an approved EEI became

## Load it

```bash
psql -d fraud_taxonomy -f 004_eei.sql
```

## Verify

```sql
-- new columns on observation
\d observation

-- new table
\d eei_candidate
```

## Design

- The scraper/extractor only ever proposes `eei_candidate` rows (status=pending).
- A human approves/rejects each in the workbench GUI (built next).
- Approved candidates are promoted into the live `selector_value` / `signal`
  tables, linked to the observation, which links to fraud type(s) via
  `observation_fraud_type`. Same human-in-the-loop discipline as the scraper.
