"""
staging_writer.py — Writes scraper candidates into the staging queue ONLY.

This module is the single, deliberate chokepoint between the scraper and the
database. It can write to exactly one table — staging_entry — and nothing else.
That is the structural guarantee behind "the scraper never touches live tables":
even if a source adapter misbehaves, the worst it can do is enqueue a candidate
for human review.

Connection reuses the same FT_DATABASE_URI convention as the Flask app.
Install (macOS):  pip install "psycopg[binary]"
"""

import os
import json
import psycopg

DATABASE_URI = os.environ.get(
    "FT_DATABASE_URI",
    "postgresql://localhost/fraud_taxonomy",
)


def _connect():
    return psycopg.connect(DATABASE_URI)


def write_candidates(candidates, dedupe=True):
    """
    Insert a list of candidate dicts into staging_entry as status='pending'.

    Each candidate must have: review_lane, provenance, source_url,
    source_name, payload (dict). Returns the number of rows inserted.

    If dedupe=True, skips a candidate whose (source_url, payload->>'title')
    already exists in staging_entry, so re-running a scrape doesn't pile up
    duplicates awaiting review.
    """
    inserted = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            for c in candidates:
                payload = c.get("payload", {})
                title = payload.get("title")

                if dedupe and title:
                    cur.execute(
                        """
                        SELECT 1 FROM staging_entry
                        WHERE source_url = %s
                          AND payload->>'title' = %s
                        LIMIT 1;
                        """,
                        (c.get("source_url"), title),
                    )
                    if cur.fetchone():
                        continue

                cur.execute(
                    """
                    INSERT INTO staging_entry
                        (review_lane, provenance, source_url, source_name, status, payload)
                    VALUES (%s, %s, %s, %s, 'pending', %s);
                    """,
                    (
                        c.get("review_lane", "single"),
                        c.get("provenance"),
                        c.get("source_url"),
                        c.get("source_name"),
                        json.dumps(payload),
                    ),
                )
                inserted += 1
        conn.commit()
    return inserted
