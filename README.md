# Fraud Taxonomy

A structured, expandable knowledge base of fraud and scam typologies — with a
browsable interface, a human-in-the-loop review queue, and a compliance-first
ingestion pipeline that pulls public-record fraud reporting from sanctioned
government sources.

The system is built around a simple thesis: **good fraud enforcement starts with
defining fraud precisely enough that both a human analyst and an automated
classifier can act on it.** This project models that definition layer end to end
— from sourcing raw public-record data, through human review, into a structured
taxonomy aligned with the STIX threat-intelligence standard.

---

## What it does

- **Catalogs fraud typologies in depth** — each fraud type carries narrative
  detail, tactics/techniques mapped to a recruitment-cycle model, detection
  signals, hard technical selectors (IOCs), and sociological profiles of both
  fraudsters and victims.
- **Ingests public-record fraud reporting responsibly** — a scraper that respects
  robots.txt, honors per-site crawl delays, detects and refuses bot-challenge
  pages (never bypassing them), and writes only to a staging queue.
- **Keeps a human in the loop** — nothing reaches the live taxonomy without human
  review. A two-lane review interface separates high-volume provenance-verified
  batches from narrative items that need individual reading.
- **Filters for relevance with a precision/recall dial** — a layered fraud-keyword
  filter (off → "fraud" only → general terms → all named typologies) lets the
  operator tune how much is surfaced for review.

---

## Architecture

```
  Public-record sources                Human review                Structured taxonomy
  (IC3 feed, state AG sites)                                       (STIX-aligned, PostgreSQL)
        │                                     │                            │
        ▼                                     ▼                            ▼
  ┌───────────┐   responsible    ┌──────────────────┐   approve    ┌──────────────────┐
  │  scraper  │ ───fetch+parse──▶│  staging_entry   │ ───────────▶ │  fraud_type, ttp │
  │           │   fraud-filter   │  (review queue)  │              │  signal, observation,
  └───────────┘                  └──────────────────┘              │  profiles, ...   │
                                          ▲                         └──────────────────┘
                                          │                                  │
                                    Flask web UI ◀───────browse──────────────┘
```

Three components, each independently documented:

| Component | Folder | What it is |
|---|---|---|
| **Database** | [`db/`](db/) | PostgreSQL schema (18 tables), STIX-aligned, with seed data |
| **Web app** | [`app/`](app/) | Flask + psycopg (raw SQL) — taxonomy browser + two-lane review |
| **Scraper** | [`scraper/`](scraper/) | Responsible, compliance-first ingestion from public-record sources |

A full data-model specification is in
[`Fraud_Taxonomy_Data_Model_Spec_v0.2.docx`](Fraud_Taxonomy_Data_Model_Spec_v0.2.docx).

---

## Design principles

**STIX-aligned, but human-readable.** Core objects map to the STIX 2.1
vocabulary (`fraud_type` → attack-pattern, `signal` → indicator, etc.) so the
data can interoperate with established threat-intelligence platforms — while the
app surfaces both the STIX name and a plain-English label. A generic
subject-predicate-object `relationship` table lets the taxonomy grow to represent
new fraud structures without schema changes.

**The HUMINT recruitment cycle as a TTP model.** Rather than a generic cyber
kill-chain, fraud tactics are mapped to the phases of human-source recruitment —
Spotting, Assessing, Developing, Recruiting, Handling, Termination — which
describes the fraudster-victim relationship far more naturally (a romance/
pig-butchering scam *is* a recruitment cycle).

**Detection signals as the bridge to classifiers.** A unified `signal` table
holds three detection paradigms — hash/signature, persistent selector (IP, IMEI,
crypto wallet, etc.), and behavioral — each carrying a human-readable detection
heuristic and a confidence rating. The behavioral signals are deliberately
written as the kind of guidance a classifier could be trained on.

**Sociological depth beyond STIX.** Custom `fraudster_profile` and
`victim_profile` objects capture organization type, motivation (including coerced
scam-compound labor), victim susceptibility, and — notably — trauma-informed
handling notes, recognizing that fraud victims carry shame that affects how they
report. Victim data is modeled only at the typology level; no personal data is
stored.

---

## Compliance-first ingestion

The scraper is built so that an interviewer, a lawyer, and a safeguards team
would all be comfortable with it. It was developed against real government sites,
and the sourcing decisions reflect what was actually found:

- **Respects `robots.txt`** for every host, every request.
- **Honors each site's declared `Crawl-delay`** (e.g., DoJ's requested 10s).
- **Detects bot-challenge / interstitial pages** (Cloudflare, Akamai signatures),
  refuses to treat them as content, logs them, and **never attempts to bypass a
  challenge** — a deliberate line: respecting an access control even when
  `robots.txt` alone would permit the fetch.
- **HTTPS only; honest, identifiable User-Agent; public-record sources only.**
- **Dry-run by default**; writes only ever go to the staging queue, never
  directly to the live taxonomy.

The source triage that resulted (documented in [`scraper/README.md`](scraper/README.md)):

| Source | Status |
|---|---|
| **FBI IC3** PSA feed (`ic3.gov/PSA/RSS`) | **Open** — valid RSS, fraud-specific. Federal anchor. |
| **State Attorney General sites** (28 validated) | **Open** to an honest, rate-limited agent. |
| FTC, DoJ, FBI main site | Behind enterprise bot-walls — respected, not crawled. |
| ~15 state sites | `robots.txt` disallows the news path — excluded. |

This triage — methodically testing each source with an honest agent and
*documenting what was excluded and why* — is itself part of the deliverable.

---

## Quick start

Requires PostgreSQL (tested on 18 via Postgres.app) and Python 3.10+.

```bash
# 1. Database
createdb fraud_taxonomy
psql -d fraud_taxonomy -f db/001_schema.sql
psql -d fraud_taxonomy -f db/002_seed.sql
psql -d fraud_taxonomy -f db/003_seed_staging.sql   # optional demo review data

# 2. Environment
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Web app
cd app && flask --app app run --debug
#   → http://127.0.0.1:5000

# 4. Scraper (in another terminal, venv active)
cd scraper
python scrape.py --probe --findings <your-findings-file>.xlsx     # classify sources
python scrape.py --state-ag --findings <your-findings-file>.xlsx  # preview candidates
#   add --commit to enqueue for review; --filter-level 0..3 to tune fraud filter
```

Connection defaults to a local Postgres.app database; set `FT_DATABASE_URI` to
point elsewhere (e.g., AWS RDS) with no code change.

---

## Status

Working end to end: schema, browsable app, two-lane review, and a
compliance-first scraper feeding the review queue from a validated set of
public-record sources. Active development continues on promoting reviewed items
into the structured taxonomy (fraud-type linking and TTP extraction at approval
time).

---

*Built as a working demonstration of fraud-typology modeling, responsible data
sourcing, and human-in-the-loop review — the definition-and-detection lifecycle
that underpins effective fraud and scam enforcement.*
