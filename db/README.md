# Fraud Taxonomy Database — Schema (v0.2)

PostgreSQL schema and seed data for the fraud taxonomy. Reflects review comments KK1.

## Prerequisites (macOS)

```bash
# Install PostgreSQL (Homebrew)
brew install postgresql@16
brew services start postgresql@16

# Create the database
createdb fraud_taxonomy
```

## Load the schema and seed data

```bash
psql -d fraud_taxonomy -f 001_schema.sql
psql -d fraud_taxonomy -f 002_seed.sql
```

## Verify it worked

```bash
psql -d fraud_taxonomy
```

Then run these sanity queries:

```sql
-- 1. All fraud types with their category
SELECT ft.name, c.name AS category, ft.severity
FROM fraud_type ft LEFT JOIN category c ON c.category_id = ft.category_id;

-- 2. The four tag dimensions and how many values each has
SELECT dimension, count(*) FROM tag GROUP BY dimension ORDER BY dimension;

-- 3. Pig-butchering TTPs in HUMINT-phase order
SELECT p.sort_order, p.name AS phase, t.technique
FROM ttp t
JOIN humint_phase p ON p.phase_id = t.phase_id
JOIN fraud_type ft ON ft.fraud_type_id = t.fraud_type_id
WHERE ft.name LIKE 'Romance%'
ORDER BY p.sort_order;

-- 4. Which fraud types leverage AI translation? (tag-vocabulary query)
SELECT ft.name
FROM fraud_type ft
JOIN fraud_type_tag ftt ON ftt.fraud_type_id = ft.fraud_type_id
JOIN tag t ON t.tag_id = ftt.tag_id
WHERE t.dimension = 'ai_leverage' AND t.value = 'translation';

-- 5. The behavioral signal (the Claude-usage example)
SELECT name, confidence, detection_heuristic FROM signal WHERE signal_class = 'behavioral';

-- 6. The blended observation tagged to multiple fraud types
SELECT o.title, ft.name AS tagged_type
FROM observation o
JOIN observation_fraud_type oft ON oft.observation_id = o.observation_id
JOIN fraud_type ft ON ft.fraud_type_id = oft.fraud_type_id;

-- 7. Pre-seeded external systems
SELECT name, system_type FROM external_system ORDER BY name;
```

## Connecting from the Flask app (next phase)

Connection details come from environment variables — no hardcoding — so pointing
at AWS RDS later is a one-line change:

```bash
export FT_DB_HOST=localhost
export FT_DB_NAME=fraud_taxonomy
export FT_DB_USER=$(whoami)
export FT_DB_PORT=5432
```

## Migrating to AWS RDS later

```bash
# Dump local
pg_dump fraud_taxonomy > fraud_taxonomy.sql
# Restore to RDS endpoint
psql -h <rds-endpoint> -U <user> -d fraud_taxonomy -f fraud_taxonomy.sql
```

Standard PostgreSQL types only; no local-only extensions, so this is a clean restore.

## File manifest

- `001_schema.sql` — 18 tables, indexes, full-text + JSONB GIN, updated_at triggers
- `002_seed.sql` — HUMINT phases, four tag vocabularies, two fully-worked fraud types
  (Pig Butchering, BEC), a blended observation, pre-seeded external systems
