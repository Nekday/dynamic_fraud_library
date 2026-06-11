# Migration 009 — Backfill stranded selector promotions

Data repair companion to the selector-promotion fix in `app/db.py`.

## Why it exists

The original promotion gate was `classifier_type in {email, phone, url, domain,
ip}`. Human highlight-and-assign tags a generic IOC with
`classifier_type="selector"`, which is not in that set — so those EEIs were
**approved but never promoted** to `selector_value`, and (being `eei_class=
'selector'`, not behavioral/ttp) they were also excluded from the
promote-to-library queue. A dead zone: reachable by neither promotion path.
Observed live: "Steve Dixon" in the elderly-PII case — approved, yet the
Identifying Selectors page showed nothing.

## The fix (two parts)

1. **Code** (`app/db.py`): the gate is now `eei_class == 'selector'`, resolved
   through one shared helper, `_promotable_selector_subtype()`, used by both
   promotion paths (`approve_eei`, `apply_eei_decisions`). Concrete types keep
   their subtype; generic human-tagged selectors store as subtype `'other'`.
   `'amount'` is explicitly excluded — the regex extractor classes amounts as
   `eei_class='selector'` for highlighting, but they are case facts, not
   identifiers, and must never enter the IOC library.
2. **Data** (this migration): promotes rows approved *before* the code fix.
   Idempotent; mirrors the helper's logic exactly.

## Load it

```bash
psql -d fraud_taxonomy -f 009_backfill_selector_promotions.sql
```

## Verify

```sql
-- "Steve Dixon" (and any other stranded selectors) should now appear:
SELECT selector_type, value, context FROM selector_value ORDER BY selector_type, value;

-- No approved selector-class EEIs (other than amounts) left unlinked:
SELECT count(*) FROM eei_candidate
WHERE status='approved' AND eei_class='selector'
  AND classifier_type <> 'amount' AND promoted_selector_id IS NULL;  -- expect 0
```

The Identifying Selectors page (`/selectors`) should now list the promoted
values, with human-tagged generics under type `other`.
