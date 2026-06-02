# Fraud Taxonomy — Responsible Scraper

Turns **public-record** fraud sources into **candidate entries in the staging
queue** for human review. It never writes to the live taxonomy tables.

## Responsible-use commitments

- **robots.txt respected** for every host, every request.
- **Per-site Crawl-delay honored** — reads each site's declared delay from
  robots.txt (capped at 30s), falling back to a 2s polite default.
- **Bot-challenge detection** — recognizes Cloudflare ("Just a moment...",
  `_cf_chl_opt`) and Akamai ("abusive automated request", interstitial)
  challenge pages, refuses to treat them as content, logs them, and skips.
  **It never attempts to solve or bypass a challenge.**
- **Honest User-Agent** identifying the bot and a contact address.
- **HTTPS only.** Public-record sources only. No "follow every link" crawler.
- **Dry-run by default** — writes nothing unless `--commit` is passed.
- **Staging-only writes** — even with `--commit`, the only table written is
  `staging_entry` (pending). Promotion to live tables is exclusively via human
  review in the app.

Edit the contact in `fetcher.py` (`USER_AGENT`) before real use.

## Setup (macOS)

From the project root, venv active:

```bash
pip install -r requirements.txt   # requests, beautifulsoup4, openpyxl, psycopg
```

## Fraud-relevance filter (layered, on by default)

State AGs publish far more than fraud news. A layered keyword filter keeps the
review queue focused, with a selectable precision/recall dial via `--filter-level`:

- `--filter-level 0` — OFF, keep everything
- `--filter-level 1` — just "fraud" (default; highest precision)
- `--filter-level 2` — + general fraud terms (scheme, defraud, false statements,
  material misrepresentation, money laundering, ponzi, ...)
- `--filter-level 3` — + all named typologies (romance scam, pig butchering, BEC,
  elder fraud, phishing, identity theft, gift card, crypto, robocall, imposter, ...)

Matching is case-insensitive over title + lead. Every kept candidate is tagged
with the exact keywords that matched (`payload.matched_keywords`) — an evidence
trail for the reviewer and a useful signal for future classifier training.

Edit the keyword lists freely in `fraud_filter.py`; no logic changes needed.

```bash
# State-AG batch, broadest fraud net, preview:
python scrape.py --state-ag --findings .../findings.xlsx --filter-level 3
```

## Modes

### 1. Probe (classify sources, write nothing) — run this first

Tells you which sources serve real content vs. a bot-challenge vs. robots-blocked.

```bash
# Every source in your findings file:
python scrape.py --probe \
    --findings /Users/k2/Coding/SQL_Fraud/web_validator_copilot/url-and-findings-checked_validated-kk.xlsx

# A single URL:
python scrape.py --probe --url https://www.ic3.gov/PSA/RSS
```

Statuses: `OK` (real content), `CHALLENGE` (bot-gated — respected, skipped),
`ROBOTS-BLOCKED`, `THIN/POSSIBLY-JS`, `ERROR`. Only `OK` sources are good for
live scraping.

### 2. State-AG batch (iterate your vetted findings file)

Reads the `Useable-URL` tab (XLSX) or a CSV, iterates each source, prefers an
RSS/feed URL if present, else parses the HTML listing. Each candidate is tagged
with its state + AG office as provenance.

```bash
# Preview (writes nothing):
python scrape.py --state-ag \
    --findings /Users/k2/Coding/SQL_Fraud/web_validator_copilot/url-and-findings-checked_validated-kk.xlsx

# Enqueue for review:
python scrape.py --state-ag --findings .../url-and-findings-checked_validated-kk.xlsx --commit
```

Findings-file columns are matched by **header name** (case-insensitive), so you
can add/reorder columns freely:
- `State` (required), `Working URL` (required)
- `RSS` / `Feed URL` (optional — if present, preferred over HTML)
- `Organization` / `AG` / `Office` (optional — used for provenance)

### 3. Single source (one URL, one adapter)

```bash
# IC3 PSA feed (the confirmed-open federal anchor):
python scrape.py --adapter feed --source-name "FBI IC3" \
    --provenance "IC3 PSA feed" --agency "FBI IC3" \
    --url https://www.ic3.gov/PSA/RSS

# A single state-AG news listing page (server-rendered HTML):
python scrape.py --adapter ag_listing --source-name "Example AG" \
    --provenance "Example AG (news listing)" --agency "Example AG" \
    --url https://ag.example.gov/news

# Offline test against a saved file:
python scrape.py --adapter feed --file fixtures/ftc_feed_sample.xml \
    --url https://www.ic3.gov/PSA/RSS
```

Add `--commit` to any preview to enqueue candidates.

## Source triage (as validated)

| Source | Status | Notes |
|---|---|---|
| **FBI IC3** (`ic3.gov/PSA/RSS`) | **OPEN** | Valid RSS feed, fraud-specific, server-rendered. Federal anchor. |
| **State AGs** (28+ URLs) | **MIXED** | Many open; some robots-blocked or edge-gated. Probe to confirm per-source. |
| FTC (`ftc.gov`) | GATED | Akamai bot-wall even on robots/feeds. Respected, not crawled. |
| DoJ (`justice.gov`) | GATED | Akamai interstitial; robots allows PR with Crawl-delay 10, but edge gates. |
| FBI main (`fbi.gov`) | GATED | robots open, but content paths behind Cloudflare. |
| ~15 states | DISALLOWED | robots.txt disallows the news path. Excluded. |

## Workflow

1. **Probe** your findings file to see what's actually usable today.
2. **Preview** (state-ag or single) to see candidates.
3. **Commit** to enqueue as `pending` in `staging_entry`.
4. App → **Review**: approve (promote to live) or reject. Duplicates
   (same URL + title) are skipped on re-runs.

## Files

- `fetcher.py` — robots-respecting, crawl-delay-honoring, challenge-detecting fetcher
- `sources.py` — adapters: `feed` (RSS/Atom), `ag_listing` (state AG HTML),
  `gov_alert` (single advisory), `doj_list` (legacy HTML listing)
- `source_lists.py` — reads your findings CSV/XLSX (columns by header name)
- `staging_writer.py` — the single chokepoint that writes to `staging_entry` only
- `scrape.py` — CLI: probe / state-ag / single
- `fixtures/` — saved samples for offline parser testing
