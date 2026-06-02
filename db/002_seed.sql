-- ============================================================
--  Fraud Taxonomy — Seed data (Migration 002)
--  v0.2 — HUMINT phases, four tag vocabularies, worked examples
--  Run AFTER 001_schema.sql:  psql -d fraud_taxonomy -f 002_seed.sql
-- ============================================================

BEGIN;

-- ---------- HUMINT phases ----------
INSERT INTO humint_phase (phase_id, name, sort_order, description) VALUES
 (1,'Spotting',    1,'Identifying and locating potential victims (lead lists, dating apps, marketplace trawling).'),
 (2,'Assessing',   2,'Probing susceptibility, wealth, loneliness, authority to act.'),
 (3,'Developing',  3,'Building rapport and trust; the grooming arc.'),
 (4,'Recruiting',  4,'Securing the victim''s commitment to the fraudulent premise (the ask).'),
 (5,'Handling',    5,'Ongoing exploitation and repeated extraction; sustaining the relationship.'),
 (6,'Termination', 6,'Disengagement — fraudster vanishes on confrontation, or victim is exhausted.')
ON CONFLICT (phase_id) DO NOTHING;

-- ---------- Categories ----------
INSERT INTO category (name, description) VALUES
 ('Social Engineering Scam','Fraud built primarily on manipulating a person.'),
 ('Business Email Compromise','Impersonation-driven fraudulent payment induction.'),
 ('Investment / Crypto Fraud','Fraud premised on fake investment returns.')
ON CONFLICT (name) DO NOTHING;

-- ---------- Tag vocabularies (four dimensions) ----------
INSERT INTO tag (dimension, value, description, related_selector_type) VALUES
 -- communication_vector
 ('communication_vector','telephone voice',NULL,'phone'),
 ('communication_vector','SMS/text',NULL,'phone'),
 ('communication_vector','Facebook',NULL,NULL),
 ('communication_vector','Facebook Marketplace',NULL,NULL),
 ('communication_vector','Craigslist',NULL,NULL),
 ('communication_vector','want-ads',NULL,NULL),
 ('communication_vector','email',NULL,'email'),
 ('communication_vector','dating app',NULL,NULL),
 ('communication_vector','messaging app',NULL,NULL),
 -- ai_leverage
 ('ai_leverage','translation',NULL,NULL),
 ('ai_leverage','image creation',NULL,NULL),
 ('ai_leverage','narrative production',NULL,NULL),
 ('ai_leverage','voice cloning',NULL,NULL),
 ('ai_leverage','deepfake video',NULL,NULL),
 ('ai_leverage','code generation',NULL,NULL),
 ('ai_leverage','persona automation',NULL,NULL),
 -- fraud_target
 ('fraud_target','credentials',NULL,NULL),
 ('fraud_target','retirement income',NULL,NULL),
 ('fraud_target','PII',NULL,NULL),
 ('fraud_target','government benefits',NULL,NULL),
 ('fraud_target','payment-card data',NULL,NULL),
 ('fraud_target','crypto holdings',NULL,NULL),
 ('fraud_target','corporate funds',NULL,NULL),
 -- cash_out_method (cross-referenced to selector types where applicable)
 ('cash_out_method','gift card',NULL,'gift_card_code'),
 ('cash_out_method','bank/wire transfer',NULL,'mule_account'),
 ('cash_out_method','cryptocurrency',NULL,'crypto_wallet'),
 ('cash_out_method','money mule',NULL,'mule_account'),
 ('cash_out_method','P2P payment app',NULL,NULL),
 ('cash_out_method','prepaid card',NULL,NULL)
ON CONFLICT (dimension, value) DO NOTHING;

-- ---------- Fraud type 1: Romance / Pig-Butchering ----------
INSERT INTO fraud_type (name, category_id, aliases, summary, description, typical_targets, estimated_prevalence, severity)
SELECT 'Romance Investment Scam (Pig Butchering)',
       (SELECT category_id FROM category WHERE name='Investment / Crypto Fraud'),
       'sha zhu pan, romance-crypto scam',
       'A long-con blending romantic grooming with a fraudulent investment, typically crypto, in which the victim is "fattened" before being "slaughtered".',
       'The fraudster cultivates a romantic or close relationship over weeks or months, then introduces a fraudulent investment platform showing fabricated gains to induce escalating deposits until the victim is drained and contact ceases.',
       'Adults seeking companionship online; often midlife or older; crypto-curious.',
       'Multi-billion USD annually (FBI IC3 cryptocurrency-investment category).',
       5
ON CONFLICT (name) DO NOTHING;

-- tags for pig butchering
INSERT INTO fraud_type_tag (fraud_type_id, tag_id)
SELECT ft.fraud_type_id, t.tag_id
FROM fraud_type ft, tag t
WHERE ft.name='Romance Investment Scam (Pig Butchering)'
  AND ( (t.dimension='communication_vector' AND t.value IN ('dating app','messaging app','SMS/text'))
     OR (t.dimension='ai_leverage'          AND t.value IN ('translation','narrative production','image creation'))
     OR (t.dimension='fraud_target'         AND t.value IN ('crypto holdings','retirement income'))
     OR (t.dimension='cash_out_method'      AND t.value IN ('cryptocurrency')) )
ON CONFLICT DO NOTHING;

-- TTPs across HUMINT phases
INSERT INTO ttp (fraud_type_id, phase_id, technique, description)
SELECT ft.fraud_type_id, p.phase_id, x.technique, x.descr
FROM fraud_type ft
JOIN (VALUES
   ('Spotting',    'Profile trawling on dating/social apps', 'Mass outreach to dating-app and social profiles to find responsive targets.'),
   ('Assessing',   'Wealth and loneliness probing',          'Conversational probing of finances, isolation, and openness to investing.'),
   ('Developing',  'Accelerated intimacy / love-bombing',    'Intense daily contact to build dependency and trust.'),
   ('Recruiting',  'Introduce fraudulent platform',          'Presents a "proven" crypto platform with fabricated returns; assists first deposit.'),
   ('Handling',    'Fabricated-gains reinvestment loop',     'Shows growing balances to induce escalating deposits; blocks withdrawals via "fees/taxes".'),
   ('Termination', 'Disappearance on withdrawal pressure',   'Ceases contact once funds are exhausted or victim demands withdrawal.')
) AS x(phase, technique, descr) ON TRUE
JOIN humint_phase p ON p.name = x.phase
WHERE ft.name='Romance Investment Scam (Pig Butchering)';

-- a behavioral signal (the Claude-usage example)
INSERT INTO signal (fraud_type_id, signal_class, name, detection_heuristic, pattern, confidence, ttp_phase_id, false_positive_note)
SELECT ft.fraud_type_id, 'behavioral',
       'Repetitive one-sided script across personas',
       'Single account submits near-identical opening messages in sequence, each addressed to a different persona/name, consistent with one script run against many victims.',
       '{"repetition":"high","persona_variation":true,"directionality":"one-sided"}'::jsonb,
       'medium',
       (SELECT phase_id FROM humint_phase WHERE name='Developing'),
       'Legitimate template outreach (sales, recruiting) can resemble this; weight with victim-targeting and relationship-building language.'
FROM fraud_type ft WHERE ft.name='Romance Investment Scam (Pig Butchering)';

-- victim & fraudster profiles
INSERT INTO victim_profile (fraud_type_id, demographic, susceptibility_factor, victim_motivation, typical_loss_profile, trauma_consideration)
SELECT ft.fraud_type_id, 'Adults, frequently midlife or older', 'Loneliness; trust; crypto-curiosity; sunk-cost commitment',
       'Believed they were in a genuine relationship and a legitimate, profitable investment',
       'Often life-altering: retirement savings, home equity; frequently total loss',
       'Acute shame and self-blame are typical; trauma-informed, non-judgmental interviewing is essential to obtain a full account.'
FROM fraud_type ft WHERE ft.name='Romance Investment Scam (Pig Butchering)';

INSERT INTO fraudster_profile (fraud_type_id, organization_type, motivation, sophistication, typical_origin_region, modus_narrative)
SELECT ft.fraud_type_id, 'call-center/scam-compound', 'coerced', 'high',
       'Southeast Asia compounds (often trafficked labor)',
       'Industrialized scam compounds run scripts at scale; workers may themselves be trafficking victims coerced into defrauding targets.'
FROM fraud_type ft WHERE ft.name='Romance Investment Scam (Pig Butchering)';

-- ---------- Fraud type 2: Business Email Compromise ----------
INSERT INTO fraud_type (name, category_id, aliases, summary, description, typical_targets, estimated_prevalence, severity)
SELECT 'Business Email Compromise (BEC)',
       (SELECT category_id FROM category WHERE name='Business Email Compromise'),
       'CEO fraud, executive impersonation, invoice fraud',
       'Impersonation of an executive or trusted party to induce a fraudulent wire transfer, exploiting authority and secrecy.',
       'Attacker impersonates a senior executive or vendor — via spoofed or compromised email — and pressures an employee to execute an urgent, confidential wire transfer, often timed to acquisitions or executive travel.',
       'Finance/AP staff with payment authority; firms mid-transaction.',
       'One of the highest-loss fraud categories per FBI IC3.',
       5
ON CONFLICT (name) DO NOTHING;

INSERT INTO fraud_type_tag (fraud_type_id, tag_id)
SELECT ft.fraud_type_id, t.tag_id
FROM fraud_type ft, tag t
WHERE ft.name='Business Email Compromise (BEC)'
  AND ( (t.dimension='communication_vector' AND t.value IN ('email'))
     OR (t.dimension='ai_leverage'          AND t.value IN ('narrative production','voice cloning'))
     OR (t.dimension='fraud_target'         AND t.value IN ('corporate funds'))
     OR (t.dimension='cash_out_method'      AND t.value IN ('bank/wire transfer','money mule')) )
ON CONFLICT DO NOTHING;

INSERT INTO ttp (fraud_type_id, phase_id, technique, description)
SELECT ft.fraud_type_id, p.phase_id, x.technique, x.descr
FROM fraud_type ft
JOIN (VALUES
   ('Spotting',   'Target reconnaissance', 'OSINT on org chart, finance staff, in-flight deals.'),
   ('Assessing',  'Authority-chain mapping','Identify who can authorize payments and to whom they defer.'),
   ('Developing', 'Email spoof / account compromise','Establish a credible impersonation channel.'),
   ('Recruiting', 'Urgent confidential request','Pressure the employee with secrecy and authority to wire funds.'),
   ('Handling',   'Redirect and reassure','Provide mule banking details; deflect verification.'),
   ('Termination','Funds dispersal','Rapidly layer funds through mule accounts before discovery.')
) AS x(phase, technique, descr) ON TRUE
JOIN humint_phase p ON p.name = x.phase
WHERE ft.name='Business Email Compromise (BEC)';

INSERT INTO signal (fraud_type_id, signal_class, name, detection_heuristic, pattern, confidence, ttp_phase_id, false_positive_note)
SELECT ft.fraud_type_id, 'behavioral',
       'Executive-impersonation urgency + secrecy',
       'Inbound payment request invokes senior authority, urgency, and confidentiality while discouraging out-of-band verification.',
       '{"authority_invocation":true,"urgency":true,"secrecy":true,"new_payee":true}'::jsonb,
       'medium',
       (SELECT phase_id FROM humint_phase WHERE name='Recruiting'),
       'Legitimate urgent executive requests exist; verify via independent channel rather than auto-flagging.'
FROM fraud_type ft WHERE ft.name='Business Email Compromise (BEC)';

INSERT INTO victim_profile (fraud_type_id, demographic, susceptibility_factor, victim_motivation, typical_loss_profile, trauma_consideration)
SELECT ft.fraud_type_id, 'Finance/AP employees', 'Authority deference; urgency; secrecy norms around M&A',
       'Believed they were following a legitimate executive instruction and completing a normal transaction (manipulated intermediary)',
       'Six- to eight-figure single-transfer losses',
       'Employee victims of manipulation may carry guilt; handling should separate manipulation from misconduct.'
FROM fraud_type ft WHERE ft.name='Business Email Compromise (BEC)';

-- ---------- A blended observation (public-record sourcing + multi-type) ----------
INSERT INTO observation (title, narrative, occurred_year, loss_estimate, source_url, agency, jurisdiction, retrieved_at)
VALUES (
   'Illustrative blended romance-to-crypto case',
   'Placeholder illustrative observation showing a romance approach that transitioned into a fraudulent crypto-investment platform. Replace with a sourced public-record case (e.g., DoJ press release) during data population.',
   2024, 'USD (varies)', 'https://www.justice.gov/', 'US DoJ (placeholder)', 'US', now()
);

-- tag the blended observation to BOTH fraud types
INSERT INTO observation_fraud_type (observation_id, fraud_type_id)
SELECT o.observation_id, ft.fraud_type_id
FROM observation o, fraud_type ft
WHERE o.title='Illustrative blended romance-to-crypto case'
  AND ft.name IN ('Romance Investment Scam (Pig Butchering)','Business Email Compromise (BEC)')
ON CONFLICT DO NOTHING;

-- ---------- External systems (pre-seeded registry) ----------
INSERT INTO external_system (name, system_type, description, api_config) VALUES
 ('Meta Hasher-Matcher-Actioner (HMA)','hash-db','Open-source copy-detection / hash-matching reference implementation.', '{}'::jsonb),
 ('TransUnion device intelligence','device-intel','Persistent device identification surviving SIM swap (reference only).', '{}'::jsonb),
 ('STIX/TAXII feed','taxii-feed','Structured threat-intel exchange (STIX 2.1 over TAXII 2.1).', '{}'::jsonb),
 ('CISA Automated Indicator Sharing (AIS)','taxii-feed','US government real-time indicator sharing.', '{}'::jsonb),
 ('FBI IC3 / DoJ public records','api','Public-record fraud case sources for observations.', '{}'::jsonb)
ON CONFLICT (name) DO NOTHING;

COMMIT;
