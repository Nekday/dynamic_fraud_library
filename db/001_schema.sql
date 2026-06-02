-- ============================================================
--  Fraud Taxonomy — Schema (PostgreSQL 14+)
--  Migration 001: core schema
--  v0.2 — reflects review comments KK1
--
--  Run:  psql -d fraud_taxonomy -f 001_schema.sql
--
--  Design summary:
--   * Core objects align with STIX 2.1 (mapping in comments).
--   * Unified `signal` table (hash | selector | behavioral).
--   * Four filterable tag vocabularies (many-to-many w/ fraud_type).
--   * HUMINT-cycle TTP phases.
--   * Sociological objects: fraudster_profile, victim_profile.
--   * observation: public-record sourcing + blended (multi-type).
--   * Two-lane human-in-the-loop staging.
--   * Extensible external_system / external_reference bridge.
--   * Generic relationship table (STIX SRO) for expandability.
--  All timestamps UTC (timestamptz). Standard types for RDS.
-- ============================================================

BEGIN;

-- ---------- ENUM-like phase via lookup (kept as table for extensibility) ----------
CREATE TABLE IF NOT EXISTS humint_phase (
    phase_id     SMALLINT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,     -- Spotting, Assessing, Developing, Recruiting, Handling, Termination
    sort_order   SMALLINT NOT NULL,
    description  TEXT
);

-- ---------- Controlled vocabularies ----------
CREATE TABLE IF NOT EXISTS category (
    category_id  SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT
);

-- Generic tag vocabulary: one table holds all four dimensions,
-- discriminated by `dimension`. New dimensions => just new rows.
CREATE TABLE IF NOT EXISTS tag (
    tag_id       SERIAL PRIMARY KEY,
    dimension    TEXT NOT NULL
                 CHECK (dimension IN ('communication_vector','ai_leverage','fraud_target','cash_out_method')),
    value        TEXT NOT NULL,
    description  TEXT,
    -- for cash_out_method, optionally link to the matching selector type
    related_selector_type TEXT,
    UNIQUE (dimension, value)
);

-- ---------- Spine: fraud_type  (STIX: attack-pattern) ----------
CREATE TABLE IF NOT EXISTS fraud_type (
    fraud_type_id     SERIAL PRIMARY KEY,
    name              TEXT NOT NULL UNIQUE,
    stix_type         TEXT NOT NULL DEFAULT 'attack-pattern',
    category_id       INTEGER REFERENCES category(category_id) ON DELETE SET NULL,
    aliases           TEXT,
    summary           TEXT NOT NULL,
    description       TEXT,
    typical_targets   TEXT,
    estimated_prevalence TEXT,
    severity          SMALLINT CHECK (severity BETWEEN 1 AND 5),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- fraud_type <-> tag  (many-to-many across all four dimensions)
CREATE TABLE IF NOT EXISTS fraud_type_tag (
    fraud_type_id  INTEGER NOT NULL REFERENCES fraud_type(fraud_type_id) ON DELETE CASCADE,
    tag_id         INTEGER NOT NULL REFERENCES tag(tag_id) ON DELETE CASCADE,
    PRIMARY KEY (fraud_type_id, tag_id)
);

-- ---------- Signal  (STIX: indicator) ----------
-- The heart: unified detection signals across three paradigms.
CREATE TABLE IF NOT EXISTS signal (
    signal_id          SERIAL PRIMARY KEY,
    fraud_type_id      INTEGER REFERENCES fraud_type(fraud_type_id) ON DELETE CASCADE,
    signal_class       TEXT NOT NULL CHECK (signal_class IN ('hash','selector','behavioral')),
    name               TEXT NOT NULL,
    detection_heuristic TEXT,            -- human-readable rule (classifier-guideline language)
    pattern            JSONB,            -- class-specific structured detail
    confidence         TEXT CHECK (confidence IN ('low','medium','high')),
    ttp_phase_id       SMALLINT REFERENCES humint_phase(phase_id) ON DELETE SET NULL,
    false_positive_note TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Selector values  (STIX: observed-data / cyber-observable) ----------
CREATE TABLE IF NOT EXISTS selector_value (
    selector_id    SERIAL PRIMARY KEY,
    selector_type  TEXT NOT NULL,        -- ip | imei | mac | crypto_wallet | mule_account | phone | domain | email | gift_card_code
    value          TEXT NOT NULL,
    fraud_type_id  INTEGER REFERENCES fraud_type(fraud_type_id) ON DELETE SET NULL,
    signal_id      INTEGER REFERENCES signal(signal_id) ON DELETE SET NULL,
    context        TEXT,
    first_seen     TIMESTAMPTZ,
    last_seen      TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (selector_type, value)
);

-- ---------- TTP  (STIX: attack-pattern / course-of-action) ----------
CREATE TABLE IF NOT EXISTS ttp (
    ttp_id         SERIAL PRIMARY KEY,
    fraud_type_id  INTEGER NOT NULL REFERENCES fraud_type(fraud_type_id) ON DELETE CASCADE,
    phase_id       SMALLINT REFERENCES humint_phase(phase_id) ON DELETE SET NULL,
    technique      TEXT NOT NULL,
    description    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Sociological objects ----------
-- fraudster_profile (STIX: threat-actor / identity, extended)
CREATE TABLE IF NOT EXISTS fraudster_profile (
    fraudster_profile_id SERIAL PRIMARY KEY,
    fraud_type_id       INTEGER REFERENCES fraud_type(fraud_type_id) ON DELETE CASCADE,
    organization_type   TEXT,    -- lone actor | organized crime | state-affiliated | call-center/scam-compound
    motivation          TEXT,    -- financial | ideological | coerced
    sophistication      TEXT CHECK (sophistication IN ('low','medium','high')),
    typical_origin_region TEXT,
    modus_narrative     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- victim_profile (custom; typology-level sociology only, NO PII)
CREATE TABLE IF NOT EXISTS victim_profile (
    victim_profile_id   SERIAL PRIMARY KEY,
    fraud_type_id       INTEGER REFERENCES fraud_type(fraud_type_id) ON DELETE CASCADE,
    demographic         TEXT,
    susceptibility_factor TEXT,
    victim_motivation   TEXT,    -- includes manipulated-intermediary motivations
    typical_loss_profile TEXT,
    trauma_consideration TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Observation  (STIX: sighting / observed-data) ----------
CREATE TABLE IF NOT EXISTS observation (
    observation_id  SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    narrative       TEXT,
    occurred_year   INTEGER,
    loss_estimate   TEXT,
    -- public-record sourcing (KK: DoJ / global LE / public domain)
    source_url      TEXT,
    agency          TEXT,         -- e.g. US DoJ, FBI IC3, RCMP, Europol
    case_identifier TEXT,
    jurisdiction    TEXT,
    retrieved_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- observation <-> fraud_type  (many-to-many: blended scams)
CREATE TABLE IF NOT EXISTS observation_fraud_type (
    observation_id INTEGER NOT NULL REFERENCES observation(observation_id) ON DELETE CASCADE,
    fraud_type_id  INTEGER NOT NULL REFERENCES fraud_type(fraud_type_id) ON DELETE CASCADE,
    PRIMARY KEY (observation_id, fraud_type_id)
);

-- ---------- Example (human-readable case writeups) ----------
CREATE TABLE IF NOT EXISTS example (
    example_id     SERIAL PRIMARY KEY,
    fraud_type_id  INTEGER NOT NULL REFERENCES fraud_type(fraud_type_id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    narrative      TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Source (STIX: external-reference) ----------
CREATE TABLE IF NOT EXISTS source (
    source_id      SERIAL PRIMARY KEY,
    fraud_type_id  INTEGER REFERENCES fraud_type(fraud_type_id) ON DELETE CASCADE,
    title          TEXT,
    publisher      TEXT,
    url            TEXT,
    retrieved_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- External-system / API bridge ----------
CREATE TABLE IF NOT EXISTS external_system (
    external_system_id SERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    system_type    TEXT,        -- hash-db | device-intel | taxii-feed | api | other
    description    TEXT,
    api_config     JSONB,       -- per-API connection detail, added as discovered
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS external_reference (
    external_reference_id SERIAL PRIMARY KEY,
    external_system_id INTEGER NOT NULL REFERENCES external_system(external_system_id) ON DELETE CASCADE,
    signal_id      INTEGER REFERENCES signal(signal_id) ON DELETE CASCADE,
    observation_id INTEGER REFERENCES observation(observation_id) ON DELETE CASCADE,
    reference_key  TEXT,        -- the external ID / pointer (NOT the proprietary data)
    note           TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (signal_id IS NOT NULL OR observation_id IS NOT NULL)
);

-- ---------- Generic relationship (STIX: SRO) ----------
-- Links ANY object to ANY other; this is the expandability mechanism.
CREATE TABLE IF NOT EXISTS relationship (
    relationship_id SERIAL PRIMARY KEY,
    source_table    TEXT NOT NULL,
    source_id       INTEGER NOT NULL,
    predicate       TEXT NOT NULL,     -- e.g. 'uses', 'targets', 'indicates', 'attributed-to'
    target_table    TEXT NOT NULL,
    target_id       INTEGER NOT NULL,
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Two-lane human-in-the-loop staging ----------
CREATE TABLE IF NOT EXISTS staging_entry (
    staging_id     SERIAL PRIMARY KEY,
    review_lane    TEXT NOT NULL DEFAULT 'single'
                   CHECK (review_lane IN ('bulk','single')),
    provenance     TEXT,        -- source/feed identity; basis for bulk trust-approval
    source_url     TEXT,
    source_name    TEXT,
    scraped_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','approved','rejected')),
    payload        JSONB NOT NULL,
    reviewer_note  TEXT,
    reviewed_at    TIMESTAMPTZ
);

-- ---------- Indexes ----------
CREATE INDEX IF NOT EXISTS idx_fraud_type_category   ON fraud_type(category_id);
CREATE INDEX IF NOT EXISTS idx_ftt_tag               ON fraud_type_tag(tag_id);
CREATE INDEX IF NOT EXISTS idx_signal_fraud_type     ON signal(fraud_type_id);
CREATE INDEX IF NOT EXISTS idx_signal_class          ON signal(signal_class);
CREATE INDEX IF NOT EXISTS idx_selector_type         ON selector_value(selector_type);
CREATE INDEX IF NOT EXISTS idx_ttp_fraud_type        ON ttp(fraud_type_id);
CREATE INDEX IF NOT EXISTS idx_oft_fraud_type        ON observation_fraud_type(fraud_type_id);
CREATE INDEX IF NOT EXISTS idx_staging_status        ON staging_entry(status);
CREATE INDEX IF NOT EXISTS idx_staging_lane          ON staging_entry(review_lane);
CREATE INDEX IF NOT EXISTS idx_rel_source            ON relationship(source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_rel_target            ON relationship(target_table, target_id);

-- Full-text search across the spine
CREATE INDEX IF NOT EXISTS idx_fraud_type_fts
    ON fraud_type USING GIN (to_tsvector('english',
        coalesce(name,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(description,'')));

-- JSONB GIN for flexible signal pattern queries
CREATE INDEX IF NOT EXISTS idx_signal_pattern        ON signal USING GIN (pattern);

-- ---------- updated_at trigger ----------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_fraud_type_updated ON fraud_type;
CREATE TRIGGER trg_fraud_type_updated
    BEFORE UPDATE ON fraud_type
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_signal_updated ON signal;
CREATE TRIGGER trg_signal_updated
    BEFORE UPDATE ON signal
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
