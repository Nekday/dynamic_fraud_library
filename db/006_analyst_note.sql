-- ============================================================
--  Fraud Taxonomy — Migration 006: case-level analyst note
--
--  A free-text commentary field on the case (observation) for the analyst's
--  own narrative. Works alongside "note" clippings (note-type eei_candidate
--  rows): the clippings are quoted passages pulled from the source; this field
--  is where the analyst writes their assessment around them.
--
--  Run AFTER 005:  psql -d fraud_taxonomy -f 006_analyst_note.sql
-- ============================================================

BEGIN;

ALTER TABLE observation
    ADD COLUMN IF NOT EXISTS analyst_note TEXT;

-- Allow 'note' as an eei_class (parked clippings the analyst pulls from the
-- source). The original 004 check allowed only selector/behavioral/ttp.
-- Drop whatever CHECK constraint currently governs eei_class (its auto-name
-- may vary), then add the widened one. Done in a DO block so we can look up
-- the real constraint name from the catalog.
DO $$
DECLARE
    cname text;
BEGIN
    SELECT con.conname INTO cname
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = 'eei_candidate'
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ILIKE '%eei_class%';
    IF cname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE eei_candidate DROP CONSTRAINT %I', cname);
    END IF;
END $$;

ALTER TABLE eei_candidate
    ADD CONSTRAINT eei_candidate_eei_class_check
    CHECK (eei_class IN ('selector','behavioral','ttp','note'));

COMMIT;
