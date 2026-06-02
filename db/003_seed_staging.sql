-- ============================================================
--  Fraud Taxonomy — Optional staging demo data (Migration 003)
--  Gives the two-lane review screen something to show.
--  Run AFTER 002_seed.sql:  psql -d fraud_taxonomy -f 003_seed_staging.sql
-- ============================================================
BEGIN;

-- SINGLE-review lane: narrative candidates, reviewed one at a time
INSERT INTO staging_entry (review_lane, provenance, source_url, source_name, status, payload) VALUES
 ('single','DoJ press release','https://www.justice.gov/','US DoJ','pending',
  '{"proposed":"fraud_type","name":"Pig-butchering variant: fake mining pool","summary":"Victims induced to join a fraudulent crypto mining pool after romance grooming."}'::jsonb),
 ('single','FTC consumer alert','https://www.ftc.gov/','US FTC','pending',
  '{"proposed":"signal","signal_class":"behavioral","name":"Urgency + gift-card cash-out instruction","heuristic":"Message pressures immediate payment specifically via retail gift-card codes."}'::jsonb);

-- BULK lane: deterministic list data, trust-approved by provenance
INSERT INTO staging_entry (review_lane, provenance, source_url, source_name, status, payload) VALUES
 ('bulk','GIFCT/HMA hash batch 2026-06','https://gifct.org/','HMA','pending',
  '{"proposed":"signal","signal_class":"hash","hash":"PLACEHOLDER_SHA256_1"}'::jsonb),
 ('bulk','GIFCT/HMA hash batch 2026-06','https://gifct.org/','HMA','pending',
  '{"proposed":"signal","signal_class":"hash","hash":"PLACEHOLDER_SHA256_2"}'::jsonb),
 ('bulk','GIFCT/HMA hash batch 2026-06','https://gifct.org/','HMA','pending',
  '{"proposed":"signal","signal_class":"hash","hash":"PLACEHOLDER_SHA256_3"}'::jsonb);

COMMIT;
