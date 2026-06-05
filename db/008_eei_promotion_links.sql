-- ============================================================
--  Fraud Taxonomy — Migration 008: EEI→signal/ttp promotion provenance
--
--  3c promotes approved behavioral/TTP EEIs into the type-linked signal/ttp
--  library. Because a case can link to several fraud types, one EEI can become
--  several signals/ttps (one per type). These link tables record that
--  provenance so we can (a) avoid duplicate promotion on re-run and
--  (b) trace any library signal back to the case + exact text it came from.
--
--  Run AFTER 007:  psql -d fraud_taxonomy -f 008_eei_promotion_links.sql
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS eei_signal_link (
    eei_id     INTEGER NOT NULL REFERENCES eei_candidate(eei_id) ON DELETE CASCADE,
    signal_id  INTEGER NOT NULL REFERENCES signal(signal_id) ON DELETE CASCADE,
    PRIMARY KEY (eei_id, signal_id)
);

CREATE TABLE IF NOT EXISTS eei_ttp_link (
    eei_id  INTEGER NOT NULL REFERENCES eei_candidate(eei_id) ON DELETE CASCADE,
    ttp_id  INTEGER NOT NULL REFERENCES ttp(ttp_id) ON DELETE CASCADE,
    PRIMARY KEY (eei_id, ttp_id)
);

COMMIT;
