#!/usr/bin/env python3
"""
scrape.py — Command-line entry point for the fraud-taxonomy scraper.

MODES
  Single source (fetch one URL with a chosen adapter):
      --adapter {feed,ag_listing,gov_alert,doj_list}  --url ...   [--commit]

  State-AG batch (read your vetted findings file, iterate compliant sources):
      --state-ag  --findings /path/to/url-and-findings-checked_validated-kk.xlsx
      [--commit]

  Probe (test each source once; report real-content / challenge / blocked;
         writes NOTHING ever):
      --probe --findings /path/to/findings.(xlsx|csv)
      (or --probe --url ... for a single source)

SAFETY MODEL (unchanged across all modes)
  * Dry-run by default; --commit required to write, and only ever to
    staging_entry (pending) — never to live taxonomy tables.
  * HTTPS only; robots.txt respected; per-site Crawl-delay honored.
  * Bot-challenge pages (Cloudflare/Akamai) are detected and skipped, never
    bypassed.

EXAMPLES
  # IC3 PSA feed (preview):
  python scrape.py --adapter feed --source-name "FBI IC3" \
      --provenance "IC3 PSA feed" --agency "FBI IC3" \
      --url https://www.ic3.gov/PSA/RSS

  # Probe every state-AG source in the findings file (writes nothing):
  python scrape.py --probe \
      --findings /Users/k2/Coding/SQL_Fraud/web_validator_copilot/url-and-findings-checked_validated-kk.xlsx

  # Run the state-AG batch and enqueue candidates for review:
  python scrape.py --state-ag \
      --findings /Users/k2/Coding/SQL_Fraud/web_validator_copilot/url-and-findings-checked_validated-kk.xlsx \
      --commit
"""

import argparse
import sys

from fetcher import ResponsibleFetcher, FetchError, ChallengeDetected
from sources import ADAPTERS, GenericGovAlertAdapter, FeedAdapter, AGListingAdapter
import source_lists
import fraud_filter
# staging_writer (imports psycopg) is imported lazily, only when --commit is used.


def build_adapter(name, source_name=None, provenance=None, agency=None):
    if name not in ADAPTERS:
        sys.exit(f"Unknown adapter '{name}'. Choices: {', '.join(ADAPTERS)}")
    cls = ADAPTERS[name]
    if cls in (GenericGovAlertAdapter, FeedAdapter, AGListingAdapter):
        return cls(source_name=source_name, provenance=provenance, agency=agency)
    return cls()


def print_candidates(candidates, adapter):
    print(f"\nAdapter: {adapter.__class__.__name__}   Source: {adapter.source_name}   "
          f"Lane: {adapter.review_lane}")
    print(f"Found {len(candidates)} candidate(s):\n")
    for i, c in enumerate(candidates, 1):
        p = c["payload"]
        print(f"[{i}] {p.get('title','(no title)')}")
        print(f"    url: {c['source_url']}")
        if p.get("date_text"):
            print(f"    date: {p['date_text']}")
        if p.get("lead"):
            lead = p["lead"]
            print(f"    lead: {lead[:160]}{'…' if len(lead) > 160 else ''}")
        print()


def write(candidates, dedupe=True):
    import staging_writer  # lazy: only needed when actually writing
    n = staging_writer.write_candidates(candidates, dedupe=dedupe)
    print(f"Wrote {n} new candidate(s) to the staging queue (status=pending). "
          f"{len(candidates) - n} skipped as duplicates.")


# ----------------------------------------------------------------------
#  Probe mode: classify each source, write nothing
# ----------------------------------------------------------------------

def probe_one(fetcher, url):
    """Return (status, detail) for a single URL without writing anything."""
    try:
        body = fetcher.get(url)
    except ChallengeDetected as e:
        return ("CHALLENGE", str(e))
    except FetchError as e:
        msg = str(e)
        if "robots.txt" in msg:
            return ("ROBOTS-BLOCKED", msg)
        return ("ERROR", msg)
    # got real content; quick heuristic for JS-only shells
    if len(body) < 3000 and ("<script" in body.lower() and body.lower().count("<p") < 2):
        return ("THIN/POSSIBLY-JS", f"{len(body)} bytes, few content tags")
    return ("OK", f"{len(body)} bytes of real content")


def run_probe(args):
    fetcher = ResponsibleFetcher()
    targets = []
    if args.url:
        targets.append(("(single)", args.url))
    elif args.findings:
        for s in source_lists.load_sources(args.findings):
            url = s["feed_url"] or s["html_url"]
            targets.append((s["state"], url))
    else:
        sys.exit("--probe needs --url or --findings.")

    print(f"Probing {len(targets)} source(s). Writes nothing.\n")
    print(f"{'STATUS':18} {'SOURCE':16} URL")
    print("-" * 80)
    summary = {}
    for label, url in targets:
        status, detail = probe_one(fetcher, url)
        summary[status] = summary.get(status, 0) + 1
        print(f"{status:18} {label:16} {url}")
    print("-" * 80)
    print("Summary:", ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))
    print("\nOnly sources marked OK are good candidates for live scraping.")


# ----------------------------------------------------------------------
#  State-AG batch mode
# ----------------------------------------------------------------------

def run_state_ag(args):
    if not args.findings:
        sys.exit("--state-ag needs --findings pointing at your CSV/XLSX.")
    sources = source_lists.load_sources(args.findings)
    print(f"Loaded {len(sources)} vetted source(s) from {args.findings}\n")

    fetcher = ResponsibleFetcher()
    all_candidates = []
    skipped = []

    for s in sources:
        state = s["state"]
        org = s["organization"]
        use_feed = bool(s["feed_url"])
        url = s["feed_url"] or s["html_url"]
        adapter = build_adapter(
            "feed" if use_feed else "ag_listing",
            source_name=org,
            provenance=f"{org} ({'feed' if use_feed else 'news listing'})",
            agency=org,
        )
        try:
            body = fetcher.get(url)
        except ChallengeDetected as e:
            skipped.append((state, "challenge-gated", url))
            print(f"  [skip] {state}: bot-challenge gate — respected, not bypassed.")
            continue
        except FetchError as e:
            reason = "robots-blocked" if "robots.txt" in str(e) else "fetch-error"
            skipped.append((state, reason, url))
            print(f"  [skip] {state}: {reason}.")
            continue

        cands = adapter.parse(body, url)
        print(f"  [ok]   {state}: {len(cands)} candidate(s) from {'feed' if use_feed else 'listing'}.")
        all_candidates.extend(cands)

    # Apply the layered fraud-relevance filter
    level = args.filter_level
    if level > 0:
        kept, dropped = fraud_filter.filter_candidates(all_candidates, level)
        print(f"\nFraud filter (level {level}): kept {len(kept)}, dropped {dropped} "
              f"of {len(all_candidates)} as not fraud-relevant.")
        all_candidates = kept
    else:
        print(f"\nFraud filter: OFF (level 0) — keeping all {len(all_candidates)}.")

    print(f"\nTotal candidates: {len(all_candidates)}   Skipped sources: {len(skipped)}")
    if skipped:
        print("Skipped (respected access controls / errors):")
        for st, why, url in skipped:
            print(f"    {st:16} {why:16} {url}")

    if not all_candidates:
        print("\nNothing to write.")
        return
    if not args.commit:
        print("\nDRY RUN — nothing written. Re-run with --commit to enqueue for review.")
        return
    write(all_candidates, dedupe=not args.no_dedupe)
    print("Review them in the app: Review → Single review.")


# ----------------------------------------------------------------------
#  Single-source mode
# ----------------------------------------------------------------------

def run_single(args):
    adapter = build_adapter(args.adapter, args.source_name, args.provenance, args.agency)
    fetcher = ResponsibleFetcher()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            body = f.read()
    elif args.url:
        try:
            body = fetcher.get(args.url)
        except ChallengeDetected as e:
            sys.exit(f"Bot-challenge gate detected — respected, not bypassed.\n{e}")
        except FetchError as e:
            sys.exit(f"Fetch refused/failed: {e}")
    else:
        sys.exit("Provide --url (to fetch) or --file (to parse a local file).")

    candidates = adapter.parse(body, args.url or args.file)
    level = args.filter_level
    if level > 0:
        kept, dropped = fraud_filter.filter_candidates(candidates, level)
        print(f"Fraud filter (level {level}): kept {len(kept)}, dropped {dropped} "
              f"of {len(candidates)}.")
        candidates = kept
    print_candidates(candidates, adapter)
    if not candidates:
        print("Nothing to write.")
        return
    if not args.commit:
        print("DRY RUN — nothing written. Re-run with --commit to enqueue these "
              "for review in the app.")
        return
    write(candidates, dedupe=not args.no_dedupe)
    print("Review them in the app: Review → "
          f"{'Bulk lane' if adapter.review_lane == 'bulk' else 'Single review'}.")


def main():
    ap = argparse.ArgumentParser(description="Fraud-taxonomy responsible scraper.")
    # modes
    ap.add_argument("--state-ag", action="store_true", help="batch mode over a findings file")
    ap.add_argument("--probe", action="store_true", help="classify sources; write nothing")
    # single-source
    ap.add_argument("--adapter", help=f"single-source adapter: {', '.join(ADAPTERS)}")
    ap.add_argument("--url", help="HTTPS URL to fetch")
    ap.add_argument("--file", help="parse a local file instead of fetching")
    ap.add_argument("--source-name", help="label for configurable adapters")
    ap.add_argument("--provenance", help="provenance string")
    ap.add_argument("--agency", help="agency label")
    # batch / probe
    ap.add_argument("--findings", help="path to findings CSV or XLSX")
    # write control
    ap.add_argument("--commit", action="store_true",
                    help="write candidates to the staging queue (default: dry-run)")
    ap.add_argument("--no-dedupe", action="store_true", help="disable duplicate-skip on write")
    # fraud-relevance filter (on by default at level 1)
    ap.add_argument("--filter-level", type=int, default=1, choices=[0, 1, 2, 3],
                    help="fraud keyword filter: 0=off, 1='fraud' only (default), "
                         "2=+general fraud terms, 3=+all named typologies")
    args = ap.parse_args()

    if args.probe:
        run_probe(args)
    elif args.state_ag:
        run_state_ag(args)
    elif args.adapter:
        run_single(args)
    else:
        ap.error("Choose a mode: --adapter (single), --state-ag (batch), or --probe.")


if __name__ == "__main__":
    main()
