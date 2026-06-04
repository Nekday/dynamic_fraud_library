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


# ----------------------------------------------------------------------
#  EEI Workbench (Layer 2 — read-only display)
# ----------------------------------------------------------------------

def list_cases():
    """Observations that have captured text — the workbench case list."""
    return query("""
        SELECT o.observation_id, o.title, o.agency, o.jurisdiction_level,
               o.docket_number, o.case_name,
               length(o.captured_text) AS text_len,
               (SELECT count(*) FROM eei_candidate e
                 WHERE e.observation_id = o.observation_id) AS eei_count,
               (SELECT count(*) FROM eei_candidate e
                 WHERE e.observation_id = o.observation_id AND e.status='pending') AS pending_count
        FROM observation o
        WHERE o.captured_text IS NOT NULL
        ORDER BY o.observation_id;
    """)


def get_case(observation_id):
    """One observation with its full captured text and case identity."""
    return query("""
        SELECT observation_id, title, agency, jurisdiction, jurisdiction_level,
               docket_number, case_name, court, disambiguation_note, analyst_note,
               source_url, captured_text, captured_at
        FROM observation
        WHERE observation_id = %s;
    """, (observation_id,), one=True)


def get_eei_candidates(observation_id):
    """EEI candidates for a case, ordered by position in the text."""
    return query("""
        SELECT eei_id, classifier_type, eei_class, matched_value, highlight_text,
               start_offset, end_offset, origin, status, note, confidence
        FROM eei_candidate
        WHERE observation_id = %s
        ORDER BY start_offset NULLS LAST, eei_id;
    """, (observation_id,))


# ----------------------------------------------------------------------
#  EEI Workbench — 3a: approve / reject / promote
# ----------------------------------------------------------------------

# Which EEI classifier types are true pivotable selectors (IOCs) that promote
# into selector_value. 'amount' is a case fact, not a selector, so it is
# recorded as approved but not promoted. 'behavioral'/'ttp' are handled later.
_SELECTOR_TYPES = {"email", "phone", "url", "domain", "ip"}


def get_eei(eei_id):
    return query("SELECT * FROM eei_candidate WHERE eei_id = %s;", (eei_id,), one=True)


def reject_eei(eei_id):
    """Mark a single EEI candidate rejected."""
    execute("""
        UPDATE eei_candidate
        SET status='rejected', reviewed_at=now()
        WHERE eei_id = %s;
    """, (eei_id,))


def approve_eei(eei_id):
    """
    Approve a single EEI candidate.
      * Selector types (email/phone/url/domain/ip) -> upsert into selector_value,
        link the candidate to the created/existing selector row.
      * Other types (amount, behavioral, ttp) -> just mark approved (recorded as
        a confirmed case fact; not promoted to selector_value).
    Done in one transaction so the candidate and any selector row stay consistent.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM eei_candidate WHERE eei_id=%s FOR UPDATE;", (eei_id,))
            row = cur.fetchone()
            if not row:
                return None
            ctype = row["classifier_type"]
            value = row["matched_value"] or row["highlight_text"]

            selector_id = None
            if ctype in _SELECTOR_TYPES and value:
                # Upsert: reuse an existing selector with same (type,value), else create.
                cur.execute(
                    "SELECT selector_id FROM selector_value WHERE selector_type=%s AND value=%s;",
                    (ctype, value),
                )
                hit = cur.fetchone()
                if hit:
                    selector_id = hit["selector_id"]
                else:
                    cur.execute(
                        """
                        INSERT INTO selector_value (selector_type, value, context, created_at)
                        VALUES (%s, %s, %s, now())
                        RETURNING selector_id;
                        """,
                        (ctype, value, f"from observation #{row['observation_id']}"),
                    )
                    selector_id = cur.fetchone()["selector_id"]

            cur.execute(
                """
                UPDATE eei_candidate
                SET status='approved', reviewed_at=now(), promoted_selector_id=%s
                WHERE eei_id=%s;
                """,
                (selector_id, eei_id),
            )
        conn.commit()
    return selector_id


def bulk_eei_action(observation_id, action, only_type=None):
    """
    Approve or reject all PENDING candidates for a case (optionally filtered to
    one classifier_type). Returns the count affected. Approvals route through
    approve_eei so selector promotion still happens per row.
    """
    pend = query("""
        SELECT eei_id, classifier_type FROM eei_candidate
        WHERE observation_id=%s AND status='pending'
        {} ;
    """.format("AND classifier_type=%s" if only_type else ""),
        (observation_id, only_type) if only_type else (observation_id,))
    n = 0
    for r in pend:
        if action == "approve":
            approve_eei(r["eei_id"])
        elif action == "reject":
            reject_eei(r["eei_id"])
        n += 1
    return n


def apply_eei_decisions(observation_id, decisions):
    """
    Apply a batch of staged review decisions in ONE transaction (R1).

    `decisions` is a dict {eei_id: 'approved'|'rejected'|'pending'}. This lets
    the reviewer stage/toggle choices in the browser and commit them all at
    once — and a single decision can be changed right up until submit, including
    back to 'pending' (which un-does a prior approve/reject and clears any
    promoted selector link).

    Returns a summary dict of counts. Selector promotion for approved
    selector-type EEIs happens here, deduped against selector_value.
    """
    summary = {"approved": 0, "rejected": 0, "reset": 0, "promoted": 0}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for eei_id, target in decisions.items():
                cur.execute("SELECT * FROM eei_candidate WHERE eei_id=%s AND observation_id=%s FOR UPDATE;",
                            (eei_id, observation_id))
                row = cur.fetchone()
                if not row:
                    continue

                if target == "approved":
                    selector_id = row.get("promoted_selector_id")
                    ctype = row["classifier_type"]
                    value = row["matched_value"] or row["highlight_text"]
                    if ctype in _SELECTOR_TYPES and value and not selector_id:
                        cur.execute("SELECT selector_id FROM selector_value WHERE selector_type=%s AND value=%s;",
                                    (ctype, value))
                        hit = cur.fetchone()
                        if hit:
                            selector_id = hit["selector_id"]
                        else:
                            cur.execute(
                                """INSERT INTO selector_value (selector_type, value, context, created_at)
                                   VALUES (%s,%s,%s, now()) RETURNING selector_id;""",
                                (ctype, value, f"from observation #{observation_id}"))
                            selector_id = cur.fetchone()["selector_id"]
                            summary["promoted"] += 1
                    cur.execute("""UPDATE eei_candidate
                                   SET status='approved', reviewed_at=now(), promoted_selector_id=%s
                                   WHERE eei_id=%s;""", (selector_id, eei_id))
                    summary["approved"] += 1

                elif target == "rejected":
                    cur.execute("""UPDATE eei_candidate
                                   SET status='rejected', reviewed_at=now()
                                   WHERE eei_id=%s;""", (eei_id,))
                    summary["rejected"] += 1

                elif target == "pending":
                    # Un-do: reset to pending and clear any promotion link.
                    # (The promoted selector row is left in place; it may be
                    # shared by other cases. A future cleanup pass can prune
                    # orphaned selectors if desired.)
                    cur.execute("""UPDATE eei_candidate
                                   SET status='pending', reviewed_at=NULL, promoted_selector_id=NULL
                                   WHERE eei_id=%s;""", (eei_id,))
                    summary["reset"] += 1
        conn.commit()
    return summary


# ----------------------------------------------------------------------
#  EEI Workbench — 3b: human highlight-and-assign (semantic EEIs)
# ----------------------------------------------------------------------

# Map a chosen semantic type to the eei_class it belongs to (determines how it
# promotes later). 'selector' covers human-spotted IOCs the regex missed.
_SEMANTIC_CLASS = {
    "behavioral":      "behavioral",
    "victim_profile":  "behavioral",   # profiles ride the behavioral class for now
    "fraudster_profile": "behavioral",
    "ttp":             "ttp",
    "selector":        "selector",
    "note":            "note",          # parked clipping; never promoted to signals/selectors
}


def add_human_eeis(observation_id, highlight_text, start_offset, end_offset, types,
                   status="approved", note=None):
    """
    Create one human-origin eei_candidate per chosen type for a single
    highlighted span (3b). One span can carry multiple tags (e.g. behavioral +
    ttp), so `types` is a list; each becomes its own atomic EEI row sharing the
    same text and offsets.

    Validates offsets against the observation's captured_text so a stale or
    malformed selection can't store a misaligned highlight. Returns the list of
    new eei_ids (or raises ValueError on bad offsets).
    """
    case = query("SELECT captured_text FROM observation WHERE observation_id=%s;",
                 (observation_id,), one=True)
    if not case or case["captured_text"] is None:
        raise ValueError("Observation has no captured text.")
    text = case["captured_text"]

    # Offset sanity: must be in range and must slice back to the submitted text.
    if not (isinstance(start_offset, int) and isinstance(end_offset, int)
            and 0 <= start_offset < end_offset <= len(text)):
        raise ValueError(f"Offsets out of range (0..{len(text)}).")
    if text[start_offset:end_offset] != highlight_text:
        raise ValueError("Offsets do not match the submitted highlight text "
                         "(text may have changed).")

    valid_types = [t for t in types if t in _SEMANTIC_CLASS]
    if not valid_types:
        raise ValueError("No valid types supplied.")

    new_ids = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            for t in valid_types:
                eei_class = _SEMANTIC_CLASS[t]
                cur.execute(
                    """
                    INSERT INTO eei_candidate
                        (observation_id, classifier_type, eei_class, matched_value,
                         highlight_text, start_offset, end_offset, origin, status,
                         note, reviewed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'human',%s,%s,
                            CASE WHEN %s='approved' THEN now() ELSE NULL END)
                    RETURNING eei_id;
                    """,
                    (observation_id, t, eei_class, highlight_text, highlight_text,
                     start_offset, end_offset, status, note, status),
                )
                new_ids.append(cur.fetchone()["eei_id"])
        conn.commit()
    return new_ids


# ----------------------------------------------------------------------
#  EEI Workbench — notes (case-level commentary + clippings)
# ----------------------------------------------------------------------

def get_note_clippings(observation_id):
    """Note-type clippings for a case, in document order (for the Notes panel)."""
    return query("""
        SELECT eei_id, highlight_text, start_offset, end_offset
        FROM eei_candidate
        WHERE observation_id=%s AND classifier_type='note'
        ORDER BY start_offset NULLS LAST, eei_id;
    """, (observation_id,))


def save_analyst_note(observation_id, text):
    """Save the case-level free-text analyst commentary."""
    execute("UPDATE observation SET analyst_note=%s WHERE observation_id=%s;",
            (text, observation_id))


def remove_eei(eei_id):
    """Delete an EEI candidate (used to un-clip a note or remove a tag)."""
    execute("DELETE FROM eei_candidate WHERE eei_id=%s;", (eei_id,))


# ----------------------------------------------------------------------
#  Fraud-type hierarchy (self-referencing tree)
# ----------------------------------------------------------------------

def list_fraud_type_tree():
    """
    Return all fraud types with parent linkage and depth, ordered for display
    as an indented tree (top-level alphabetical, children under each parent).
    Uses a recursive CTE to compute depth and a sortable path.
    """
    return query("""
        WITH RECURSIVE tree AS (
            SELECT fraud_type_id, name, parent_id, 0 AS depth,
                   lower(name) AS path
            FROM fraud_type
            WHERE parent_id IS NULL
          UNION ALL
            SELECT f.fraud_type_id, f.name, f.parent_id, t.depth + 1,
                   t.path || '>' || lower(f.name)
            FROM fraud_type f
            JOIN tree t ON f.parent_id = t.fraud_type_id
        )
        SELECT fraud_type_id, name, parent_id, depth, path
        FROM tree
        ORDER BY path;
    """)


def get_ancestry(fraud_type_id):
    """
    Return the chain from a type up to its root (most specific first), so a
    case linked to a sub-type can be rolled up to its ACFE parent(s).
    """
    return query("""
        WITH RECURSIVE up AS (
            SELECT fraud_type_id, name, parent_id, 0 AS step
            FROM fraud_type WHERE fraud_type_id = %s
          UNION ALL
            SELECT f.fraud_type_id, f.name, f.parent_id, u.step + 1
            FROM fraud_type f
            JOIN up u ON f.fraud_type_id = u.parent_id
        )
        SELECT fraud_type_id, name, parent_id, step FROM up ORDER BY step;
    """, (fraud_type_id,))


def add_fraud_type(name, parent_id=None, summary=None):
    """
    Add a new fraud type at any level (parent_id NULL = top-level). summary is
    NOT NULL in the schema, so a placeholder is used if none supplied.
    Returns the new fraud_type_id, or None if the name already exists.
    """
    name = (name or "").strip()
    if not name:
        return None
    existing = query("SELECT fraud_type_id FROM fraud_type WHERE lower(name)=lower(%s);",
                     (name,), one=True)
    if existing:
        return None
    row = execute("""
        INSERT INTO fraud_type (name, parent_id, summary)
        VALUES (%s, %s, %s)
        RETURNING fraud_type_id;
    """, (name, parent_id, summary or f"{name} (added by analyst)"), returning=True)
    return row["fraud_type_id"] if row else None
