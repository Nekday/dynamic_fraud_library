-- ============================================================
--  Fraud Taxonomy — Migration 005: case identity / disambiguation
--
--  Press releases (not court records) are our source, so the same
--  underlying case often appears in several releases (state, federal,
--  international). These fields give the human-in-the-loop a stable key
--  to recognize and link duplicate coverage of one case, and to keep
--  citations straight.
--
--  Capture, don't parse: court identifier formats vary too widely across
--  jurisdictions for a reliable regex, so these are free-text fields the
--  reviewer fills from the article, with a notes field to disambiguate.
--
--  Run AFTER 004:  psql -d fraud_taxonomy -f 005_case_identity.sql
-- ============================================================

BEGIN;

ALTER TABLE observation
    ADD COLUMN IF NOT EXISTS docket_number       TEXT,   -- e.g. 1:23-cr-00456 (federal) or varied state formats
    ADD COLUMN IF NOT EXISTS case_name           TEXT,   -- e.g. "United States v. Slappy's Car Wash"
    ADD COLUMN IF NOT EXISTS court                TEXT,   -- e.g. "N.D. Cal." / "Sacramento County Superior Court"
    ADD COLUMN IF NOT EXISTS jurisdiction_level   TEXT,   -- federal | state | international | local | unknown
    ADD COLUMN IF NOT EXISTS disambiguation_note  TEXT;   -- HITL notes: "same case as DoJ release 2026-05-20", etc.

-- Optional CHECK on jurisdiction_level kept loose (allow NULL/unknown);
-- a soft constraint rather than a hard enum so reviewers aren't blocked.
ALTER TABLE observation
    ADD CONSTRAINT chk_obs_jurisdiction_level
    CHECK (jurisdiction_level IS NULL OR jurisdiction_level IN
           ('federal','state','international','local','unknown'));

-- Helpful for the dedup/"same case from multiple sources" view later.
CREATE INDEX IF NOT EXISTS idx_obs_docket    ON observation(docket_number);
CREATE INDEX IF NOT EXISTS idx_obs_case_name ON observation(case_name);

COMMIT;
