"""
db.py — Data access layer for the Fraud Taxonomy app.

All SQL lives here, in plain text, so every query is visible and reviewable.
Connection details come from the FT_DATABASE_URI environment variable, with a
Postgres.app-friendly local default. Migrating to AWS RDS later = set that one
variable, no code change.

Uses psycopg (v3). Install:  pip install "psycopg[binary]"
"""

import os
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row

# Postgres.app local default: macOS user, no password, port 5432, db fraud_taxonomy
DATABASE_URI = os.environ.get(
    "FT_DATABASE_URI",
    "postgresql://localhost/fraud_taxonomy",
)


@contextmanager
def get_conn():
    """Yield a connection with dict-style rows; always closed afterward."""
    conn = psycopg.connect(DATABASE_URI, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def query(sql, params=None, one=False):
    """Run a SELECT and return a list of dict rows (or a single row if one=True)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, params=None, returning=False):
    """Run an INSERT/UPDATE/DELETE. If returning=True, return the fetched row."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            result = cur.fetchone() if returning else None
        conn.commit()
    return result


# ----------------------------------------------------------------------
#  Taxonomy reads
# ----------------------------------------------------------------------

def list_fraud_types(search=None, ai_leverage=None):
    """List fraud types, optionally full-text searched and/or filtered by an AI-leverage tag."""
    sql = """
        SELECT ft.fraud_type_id, ft.name, ft.summary, ft.severity,
               c.name AS category
        FROM fraud_type ft
        LEFT JOIN category c ON c.category_id = ft.category_id
    """
    clauses, params = [], []
    if search:
        clauses.append("""
            to_tsvector('english',
                coalesce(ft.name,'') || ' ' || coalesce(ft.summary,'') || ' ' || coalesce(ft.description,''))
            @@ plainto_tsquery('english', %s)
        """)
        params.append(search)
    if ai_leverage:
        clauses.append("""
            ft.fraud_type_id IN (
                SELECT ftt.fraud_type_id FROM fraud_type_tag ftt
                JOIN tag t ON t.tag_id = ftt.tag_id
                WHERE t.dimension = 'ai_leverage' AND t.value = %s
            )
        """)
        params.append(ai_leverage)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY ft.name;"
    return query(sql, params)


def get_fraud_type(fraud_type_id):
    return query("""
        SELECT ft.*, c.name AS category
        FROM fraud_type ft
        LEFT JOIN category c ON c.category_id = ft.category_id
        WHERE ft.fraud_type_id = %s;
    """, (fraud_type_id,), one=True)


def get_tags_for_type(fraud_type_id):
    """Return tags grouped by dimension for one fraud type."""
    rows = query("""
        SELECT t.dimension, t.value
        FROM fraud_type_tag ftt
        JOIN tag t ON t.tag_id = ftt.tag_id
        WHERE ftt.fraud_type_id = %s
        ORDER BY t.dimension, t.value;
    """, (fraud_type_id,))
    grouped = {}
    for r in rows:
        grouped.setdefault(r["dimension"], []).append(r["value"])
    return grouped


def get_ttps(fraud_type_id):
    return query("""
        SELECT p.sort_order, p.name AS phase, t.technique, t.description
        FROM ttp t
        LEFT JOIN humint_phase p ON p.phase_id = t.phase_id
        WHERE t.fraud_type_id = %s
        ORDER BY p.sort_order NULLS LAST;
    """, (fraud_type_id,))


def get_signals(fraud_type_id=None):
    """Signals for one fraud type, or all signals if fraud_type_id is None."""
    if fraud_type_id is None:
        return query("""
            SELECT s.signal_id, s.signal_class, s.name, s.detection_heuristic,
                   s.confidence, p.name AS ttp_phase, s.false_positive_note,
                   ft.name AS fraud_type
            FROM signal s
            LEFT JOIN humint_phase p ON p.phase_id = s.ttp_phase_id
            LEFT JOIN fraud_type ft ON ft.fraud_type_id = s.fraud_type_id
            ORDER BY s.signal_class, s.name;
        """)
    return query("""
        SELECT s.signal_id, s.signal_class, s.name, s.detection_heuristic,
               s.confidence, p.name AS ttp_phase, s.false_positive_note
        FROM signal s
        LEFT JOIN humint_phase p ON p.phase_id = s.ttp_phase_id
        WHERE s.fraud_type_id = %s
        ORDER BY s.signal_class, s.name;
    """, (fraud_type_id,))


def get_selectors(fraud_type_id=None):
    if fraud_type_id is None:
        return query("""
            SELECT sv.selector_id, sv.selector_type, sv.value, sv.context,
                   ft.name AS fraud_type
            FROM selector_value sv
            LEFT JOIN fraud_type ft ON ft.fraud_type_id = sv.fraud_type_id
            ORDER BY sv.selector_type, sv.value;
        """)
    return query("""
        SELECT selector_id, selector_type, value, context
        FROM selector_value
        WHERE fraud_type_id = %s
        ORDER BY selector_type, value;
    """, (fraud_type_id,))


def get_profiles(fraud_type_id):
    fraudster = query("""
        SELECT organization_type, motivation, sophistication,
               typical_origin_region, modus_narrative
        FROM fraudster_profile WHERE fraud_type_id = %s;
    """, (fraud_type_id,))
    victim = query("""
        SELECT demographic, susceptibility_factor, victim_motivation,
               typical_loss_profile, trauma_consideration
        FROM victim_profile WHERE fraud_type_id = %s;
    """, (fraud_type_id,))
    return {"fraudster": fraudster, "victim": victim}


def get_observations(fraud_type_id):
    return query("""
        SELECT o.observation_id, o.title, o.narrative, o.occurred_year,
               o.loss_estimate, o.source_url, o.agency, o.jurisdiction
        FROM observation o
        JOIN observation_fraud_type oft ON oft.observation_id = o.observation_id
        WHERE oft.fraud_type_id = %s
        ORDER BY o.occurred_year DESC NULLS LAST;
    """, (fraud_type_id,))


def ai_leverage_values():
    """Distinct AI-leverage tag values, for the filter dropdown."""
    return [r["value"] for r in query("""
        SELECT value FROM tag WHERE dimension = 'ai_leverage' ORDER BY value;
    """)]


def external_systems():
    return query("SELECT name, system_type, description FROM external_system ORDER BY name;")


# ----------------------------------------------------------------------
#  Two-lane staging review
# ----------------------------------------------------------------------

def list_staging(status="pending", lane=None):
    sql = """
        SELECT staging_id, review_lane, provenance, source_url, source_name,
               scraped_at, status, payload, reviewer_note
        FROM staging_entry
        WHERE status = %s
    """
    params = [status]
    if lane:
        sql += " AND review_lane = %s"
        params.append(lane)
    sql += " ORDER BY scraped_at DESC;"
    return query(sql, params)


def get_staging(staging_id):
    return query("SELECT * FROM staging_entry WHERE staging_id = %s;", (staging_id,), one=True)


def update_staging_status(staging_id, status, note=None):
    execute("""
        UPDATE staging_entry
        SET status = %s, reviewer_note = %s, reviewed_at = now()
        WHERE staging_id = %s;
    """, (status, note, staging_id))


def bulk_batches(status="pending"):
    """
    Summarize pending bulk-lane entries grouped by provenance, with the
    context a reviewer needs to make a trust-the-source decision:
    origin name, source URL, count, and the earliest/latest scraped timestamps.
    """
    return query("""
        SELECT provenance,
               count(*)                       AS n,
               min(scraped_at)                AS first_scraped,
               max(scraped_at)                AS last_scraped,
               (array_agg(DISTINCT source_url))[1]  AS source_url,
               (array_agg(DISTINCT source_name))[1] AS source_name
        FROM staging_entry
        WHERE review_lane = 'bulk' AND status = %s
        GROUP BY provenance
        ORDER BY provenance;
    """, (status,))


def bulk_batch_entries(provenance, status="pending", limit=None):
    """
    Return entries for one bulk provenance batch. With limit set, returns just
    the sample (first N); with limit None, returns the full batch for 'view all'.
    """
    sql = """
        SELECT staging_id, source_url, source_name, scraped_at, payload
        FROM staging_entry
        WHERE review_lane = 'bulk' AND status = %s AND provenance = %s
        ORDER BY staging_id
    """
    params = [status, provenance]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    sql += ";"
    return query(sql, params)


def bulk_update_status(provenance, status, note=None):
    """Approve/reject an entire provenance batch in the bulk lane."""
    execute("""
        UPDATE staging_entry
        SET status = %s, reviewer_note = %s, reviewed_at = now()
        WHERE review_lane = 'bulk' AND provenance = %s AND status = 'pending';
    """, (status, note, provenance))


def staging_counts():
    rows = query("""
        SELECT review_lane, status, count(*) AS n
        FROM staging_entry
        GROUP BY review_lane, status;
    """)
    return rows
