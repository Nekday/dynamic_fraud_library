-- ============================================================
--  Fraud Taxonomy — Migration 007: fraud-type hierarchy + ACFE seed
--
--  Adds a self-referencing parent_id to fraud_type so types form an
--  unlimited-depth tree: ACFE top-level categories -> operational typologies
--  -> variations. Cases link to the most specific type; ancestry (and thus
--  rollup reporting) is inferred by walking parent_id.
--
--  Seeds the 18 ACFE accepted fraud types as top-level nodes (parent_id NULL)
--  and re-parents the two existing worked typologies under them.
--
--  New top-level or sub-types can be added any time by inserting a row with
--  the appropriate parent_id (NULL = top level).
--
--  Run AFTER 006:  psql -d fraud_taxonomy -f 007_fraud_type_hierarchy.sql
-- ============================================================

BEGIN;

-- 1. Self-referencing parent link (NULL = top-level category).
ALTER TABLE fraud_type
    ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES fraud_type(fraud_type_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_fraud_type_parent ON fraud_type(parent_id);

-- 2. Seed the 18 ACFE top-level fraud types (idempotent on name).
--    summary is NOT NULL; brief authoritative descriptions provided.
INSERT INTO fraud_type (name, parent_id, summary, stix_type)
VALUES
  ('Accounting Fraud',                      NULL, 'Manipulation of accounting records or processes to misstate financial reality.', 'attack-pattern'),
  ('Asset Misappropriation',               NULL, 'Theft or misuse of an organization''s assets by those entrusted with them.', 'attack-pattern'),
  ('Bankruptcy Fraud',                     NULL, 'Concealment of assets or false statements in connection with bankruptcy proceedings.', 'attack-pattern'),
  ('Corruption',                           NULL, 'Abuse of entrusted power for private gain, including bribery and conflicts of interest.', 'attack-pattern'),
  ('Consumer Fraud',                       NULL, 'Deceptive schemes targeting individual consumers for financial gain.', 'attack-pattern'),
  ('Cyberfraud',                           NULL, 'Fraud perpetrated through computer systems, networks, or the internet.', 'attack-pattern'),
  ('Financial Institution Fraud',          NULL, 'Fraud against or through banks and other financial institutions.', 'attack-pattern'),
  ('Financial Statement Fraud',            NULL, 'Intentional misstatement or omission in financial statements to deceive users.', 'attack-pattern'),
  ('Government and Public Sector Fraud',   NULL, 'Fraud targeting government programs, funds, or public-sector entities.', 'attack-pattern'),
  ('Health Care Fraud',                    NULL, 'False or fraudulent claims and schemes within the health care system.', 'attack-pattern'),
  ('Identity Theft',                       NULL, 'Unauthorized acquisition and use of another person''s identifying information.', 'attack-pattern'),
  ('Insurance Fraud',                      NULL, 'False claims or misrepresentations to obtain improper insurance payouts.', 'attack-pattern'),
  ('Money Laundering',                     NULL, 'Concealing the origins of illegally obtained money to make it appear legitimate.', 'attack-pattern'),
  ('Payment Fraud',                        NULL, 'Unauthorized or deceptive transactions across payment channels.', 'attack-pattern'),
  ('Procurement Fraud',                    NULL, 'Fraud in the purchasing/contracting process, including bid-rigging and kickbacks.', 'attack-pattern'),
  ('Securities Fraud',                     NULL, 'Deceptive practices in securities markets, including investment-scheme fraud.', 'attack-pattern'),
  ('Tax Fraud',                            NULL, 'Willful evasion or falsification relating to tax obligations.', 'attack-pattern'),
  ('Theft of Data and Intellectual Property', NULL, 'Unauthorized taking of data, trade secrets, or intellectual property.', 'attack-pattern')
ON CONFLICT (name) DO NOTHING;

-- 3. Re-parent the two existing worked typologies under their ACFE parents.
--    Pig Butchering is a consumer-facing romance/investment con -> Consumer Fraud.
UPDATE fraud_type
   SET parent_id = (SELECT fraud_type_id FROM fraud_type WHERE name='Consumer Fraud')
 WHERE name = 'Romance Investment Scam (Pig Butchering)';

--    BEC induces fraudulent payments via impersonation -> Payment Fraud.
UPDATE fraud_type
   SET parent_id = (SELECT fraud_type_id FROM fraud_type WHERE name='Payment Fraud')
 WHERE name = 'Business Email Compromise (BEC)';

COMMIT;
