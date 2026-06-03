-- ============================================================
--  Fraud Taxonomy — Migration 004: EEI extraction layer
--
--  Adds the "Essential Elements of Information" workflow:
--   * captured_text on observation — our own stored copy of the case
--     article (for highlighting + archival; fetched on-demand at review).
--   * eei_candidate — extracted/proposed EEIs awaiting human review, with
--     character offsets for highlighting and an origin (regex/human/ai).
--     Approved candidates are promoted into selector_value / signal,
--     linked to the case (observation) and thence to fraud type(s).
--
--  Run AFTER 001-003:  psql -d fraud_taxonomy -f 004_eei.sql
-- ============================================================

BEGIN;

-- ---- 1. Store our own copy of the case text on the observation ----
ALTER TABLE observation
    ADD COLUMN IF NOT EXISTS captured_text TEXT,
    ADD COLUMN IF NOT EXISTS captured_at   TIMESTAMPTZ;

-- A staging_entry may be promoted into an observation; track the link so the
-- workbench can find (or create) the observation for a reviewed staging item.
ALTER TABLE observation
    ADD COLUMN IF NOT EXISTS staging_id INTEGER REFERENCES staging_entry(staging_id) ON DELETE SET NULL;

-- ---- 2. EEI candidates: extracted/proposed elements awaiting review ----
CREATE TABLE IF NOT EXISTS eei_candidate (
    eei_id          SERIAL PRIMARY KEY,
    observation_id  INTEGER NOT NULL REFERENCES observation(observation_id) ON DELETE CASCADE,

    -- What kind of element this is. Deterministic types map to selector_value;
    -- 'behavioral' and 'ttp' map to signal/ttp on promotion.
    classifier_type TEXT NOT NULL,        -- email | phone | url | amount | behavioral | ttp | (extensible)
    eei_class       TEXT NOT NULL DEFAULT 'selector'
                    CHECK (eei_class IN ('selector','behavioral','ttp')),

    -- The extracted value (for selectors) and/or the highlighted text span.
    matched_value   TEXT,                 -- e.g. fraudster@email.biz, $4,000,000
    highlight_text  TEXT,                 -- the exact text span shown highlighted

    -- Character offsets into observation.captured_text, for GUI highlighting.
    start_offset    INTEGER,
    end_offset      INTEGER,

    -- Where the candidate came from, and its review state.
    origin          TEXT NOT NULL DEFAULT 'regex'
                    CHECK (origin IN ('regex','human','ai')),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected')),

    -- Optional reviewer-supplied detail used when promoting a behavioral EEI
    -- into a signal (heuristic text + confidence) or selector context.
    note            TEXT,
    confidence      TEXT CHECK (confidence IN ('low','medium','high')),

    -- Promotion bookkeeping: which live rows this candidate became (if approved).
    promoted_selector_id INTEGER REFERENCES selector_value(selector_id) ON DELETE SET NULL,
    promoted_signal_id   INTEGER REFERENCES signal(signal_id) ON DELETE SET NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_eei_observation ON eei_candidate(observation_id);
CREATE INDEX IF NOT EXISTS idx_eei_status      ON eei_candidate(status);
CREATE INDEX IF NOT EXISTS idx_eei_class       ON eei_candidate(eei_class);

-- Prevent exact-duplicate deterministic candidates for the same observation
-- (same type + same value). Behavioral/human spans may legitimately repeat,
-- so this only guards rows that carry a matched_value.
CREATE UNIQUE INDEX IF NOT EXISTS uq_eei_obs_type_value
    ON eei_candidate(observation_id, classifier_type, matched_value)
    WHERE matched_value IS NOT NULL;

COMMIT;
