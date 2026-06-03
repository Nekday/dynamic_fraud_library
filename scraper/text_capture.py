#!/usr/bin/env python3
"""
text_capture.py — Capture case text, clean it, extract EEIs, optionally store.

Three input modes (Feature 1): a human can bring in content the automated
scraper can't (bot-walled federal sources), because a person reading a page in
a browser is not a scraper:

  --url   URL    : fetch via the responsible fetcher (robots/crawl-delay/challenge
                   detection all apply; only for sources that permit our agent)
  --file PATH    : parse a local .html file you saved from your browser
  --paste        : read pasted text (or piped stdin) — copy the article, feed it in

The invariant that makes highlighting work: we CLEAN first, then extract offsets
against the cleaned text, then store THAT SAME cleaned text. The stored
captured_text, the text the extractor ran on, and the text the GUI will display
are byte-for-byte identical, so every EEI offset lands correctly.

Cleanup fidelity (deliberately conservative):
  Tier 1 (structural, high fidelity): drop <script>,<style>,<nav>,<header>,
          <footer>,<form>,<aside> and similar non-article elements.
  Tier 2 (known boilerplate phrases, medium fidelity): strip a small list of
          recurring cruft lines (newsletter/translate/skip-to-content).
  Tier 3 (contextual pertinence, e.g. "is this $50k a bail amount?"): NOT done
          here — that is the human-in-the-loop's job. We never auto-strip it.

Dry-run by default (prints what it found). Pass --store to write an observation
(+ eei_candidate rows) to the database. Case-identity fields (migration 005) can
be supplied with --docket/--case-name/--court/--jurisdiction/--note.

Install: pip install requests beautifulsoup4 "psycopg[binary]"
"""

import argparse
import os
import re
import sys

from bs4 import BeautifulSoup
import eei_extractor


# ---------------------------------------------------------------
#  Cleanup pipeline
# ---------------------------------------------------------------

# Tier 1: structural elements that never contain article body.
_DROP_TAGS = ["script", "style", "nav", "header", "footer", "form",
              "aside", "noscript", "svg", "button", "iframe"]

# Tier 2: known recurring boilerplate phrases (case-insensitive substring match).
# Conservative — only lines that are clearly site chrome, not article content.
_BOILERPLATE = [
    "skip to main content",
    "subscribe to our newsletter",
    "subscribe",
    "google™ translate disclaimer",
    "this google™ translation feature is provided",
    "traducir sitio web",
    "translate website",
    "back to top",
    "share this page",
    "print this page",
]

# Tier 1.5: structural section boundaries that mark the END of the article body.
# Everything at/after these markers is OTHER cases or site chrome (e.g. DoJ's
# "Related Content" sidebar lists unrelated press releases). Truncating here
# removes whole-other-case contamination at a reliable marker — not a Tier-3
# pertinence guess. Case-insensitive; we cut at the earliest marker found.
_TRUNCATE_MARKERS = [
    "Related Content",
    "Related Press Releases",
    "Related News",
    "More News",
    "You might also be interested in",
]


def _truncate_at_boundary(text):
    """Cut text at the earliest end-of-article marker, if any."""
    low = text.lower()
    cut = None
    for marker in _TRUNCATE_MARKERS:
        idx = low.find(marker.lower())
        if idx != -1:
            cut = idx if cut is None else min(cut, idx)
    if cut is not None:
        return text[:cut].rstrip()
    return text


# DoJ (and similar) publish a stable release identifier we can offer as a
# case-id/disambiguation key. Captured, not relied upon — the HITL can override.
_RELEASE_NUMBER = re.compile(
    r"Press Release Number:\s*([0-9A-Za-z\-]+)", re.IGNORECASE
)


def detect_release_number(text):
    """Return a press-release / case identifier if the text declares one."""
    m = _RELEASE_NUMBER.search(text)
    return m.group(1).strip() if m else None


def clean_html_to_text(html):
    """Tier 1 + Tier 2 cleanup. Returns (canonical_text, metadata dict)."""
    soup = BeautifulSoup(html, "html.parser")

    # Tier 1: remove non-article structural elements entirely.
    for tag in soup(_DROP_TAGS):
        tag.decompose()

    # Prefer <main> or <article> if present (the real body); else whole doc.
    container = soup.find("main") or soup.find("article") or soup
    raw = container.get_text(" ")

    # collapse whitespace to a single canonical form
    text = " ".join(raw.split())

    # Tier 2: remove known boilerplate phrases (whole-phrase, case-insensitive).
    for phrase in _BOILERPLATE:
        text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
    text = " ".join(text.split())

    # Capture the release number from the FULL text BEFORE truncation (it often
    # sits right at the "Related Content" boundary and would otherwise be lost).
    meta = {"release_number": detect_release_number(text)}

    # Tier 1.5: truncate at end-of-article boundary (e.g. "Related Content")
    # so other-case contamination is removed before offsets are computed.
    text = _truncate_at_boundary(text)
    return text, meta


def clean_plaintext(text):
    """For --paste / already-text input: canonicalize whitespace + Tier 2. Returns (text, meta)."""
    text = " ".join((text or "").split())
    for phrase in _BOILERPLATE:
        text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    meta = {"release_number": detect_release_number(text)}
    text = _truncate_at_boundary(text)
    return text, meta


# ---------------------------------------------------------------
#  Input modes
# ---------------------------------------------------------------

def get_canonical_text(args):
    if args.url:
        from fetcher import ResponsibleFetcher, FetchError, ChallengeDetected
        try:
            html = ResponsibleFetcher().get(args.url)
        except ChallengeDetected as e:
            sys.exit(f"Bot-challenge gate — respected, not bypassed.\n{e}\n"
                     f"Tip: open the page in your browser and use --file or --paste instead.")
        except FetchError as e:
            sys.exit(f"Fetch refused/failed: {e}")
        return clean_html_to_text(html)

    if args.file:
        with open(args.file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        # if it's HTML, clean structurally; if it's plain text, just canonicalize
        if "<html" in content.lower() or "<body" in content.lower() or "<p" in content.lower():
            return clean_html_to_text(content)
        return clean_plaintext(content)

    if args.paste:
        print("Paste the article text, then press Ctrl-D (Mac/Linux) to finish:\n",
              file=sys.stderr)
        pasted = sys.stdin.read()
        return clean_plaintext(pasted)

    sys.exit("Provide one input mode: --url, --file, or --paste.")


# ---------------------------------------------------------------
#  Optional DB write
# ---------------------------------------------------------------

def store(args, canonical_text, candidates, effective_docket=None):
    import psycopg
    db_uri = os.environ.get("FT_DATABASE_URI", "postgresql://localhost/fraud_taxonomy")
    title = args.title or (canonical_text[:120] + ("…" if len(canonical_text) > 120 else ""))

    with psycopg.connect(db_uri) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO observation
                    (title, source_url, agency, jurisdiction,
                     captured_text, captured_at,
                     docket_number, case_name, court, jurisdiction_level, disambiguation_note)
                VALUES (%s,%s,%s,%s,%s, now(), %s,%s,%s,%s,%s)
                RETURNING observation_id;
                """,
                (title, args.url, args.agency, args.jurisdiction,
                 canonical_text,
                 effective_docket, args.case_name, args.court, args.jurisdiction_level, args.note),
            )
            obs_id = cur.fetchone()[0]

            for c in candidates:
                cur.execute(
                    """
                    INSERT INTO eei_candidate
                        (observation_id, classifier_type, eei_class, matched_value,
                         highlight_text, start_offset, end_offset, origin, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')
                    ON CONFLICT DO NOTHING;
                    """,
                    (obs_id, c["classifier_type"], c["eei_class"], c["matched_value"],
                     c["highlight_text"], c["start_offset"], c["end_offset"], c["origin"]),
                )
        conn.commit()
    return obs_id


# ---------------------------------------------------------------
#  Main
# ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Capture + clean + extract case text for EEI review.")
    # input modes
    ap.add_argument("--url", help="fetch this HTTPS URL via the responsible fetcher")
    ap.add_argument("--file", help="parse a local .html (or .txt) file")
    ap.add_argument("--paste", action="store_true", help="read pasted text from stdin")
    # storage
    ap.add_argument("--store", action="store_true", help="write observation + EEI candidates to the DB")
    ap.add_argument("--title", help="observation title (defaults to a text snippet)")
    ap.add_argument("--agency", help="source agency, e.g. 'US DoJ'")
    ap.add_argument("--jurisdiction", help="free-text jurisdiction, e.g. 'US'")
    # case identity (migration 005)
    ap.add_argument("--docket", help="docket number, e.g. 1:23-cr-00456")
    ap.add_argument("--case-name", dest="case_name", help='e.g. "United States v. Defendant"')
    ap.add_argument("--court", help="e.g. 'N.D. Cal.'")
    ap.add_argument("--jurisdiction-level", dest="jurisdiction_level",
                    choices=["federal", "state", "international", "local", "unknown"],
                    help="court level for dedup/disambiguation")
    ap.add_argument("--note", help="disambiguation note for the HITL")
    # preview controls
    ap.add_argument("--show-text", action="store_true", help="print the full canonical text")
    args = ap.parse_args()

    canonical, meta = get_canonical_text(args)
    candidates = eei_extractor.extract(canonical)

    # Auto-detected case identifier (e.g. DoJ "Press Release Number: 25-340").
    # Offered as the docket/case-id when the reviewer didn't supply one.
    auto_id = meta.get("release_number")
    effective_docket = args.docket or auto_id

    print(f"\n--- canonical text: {len(canonical)} chars ---")
    if args.show_text:
        print(canonical)
    else:
        print(canonical[:400] + ("…" if len(canonical) > 400 else ""))

    if auto_id:
        tag = "(used as docket/case-id)" if not args.docket else "(reviewer --docket overrides)"
        print(f"\n--- auto-detected release number: {auto_id}  {tag} ---")

    print(f"\n--- {len(candidates)} EEI candidate(s) extracted ---")
    for c in candidates:
        # verify offset alignment as we print (the critical invariant)
        ok = canonical[c["start_offset"]:c["end_offset"]] == c["matched_value"]
        flag = "" if ok else "  <!! OFFSET MISMATCH>"
        print(f"  {c['classifier_type']:8} [{c['start_offset']:>5}-{c['end_offset']:<5}] "
              f"{c['matched_value']}{flag}")

    if not args.store:
        print("\nDRY RUN — nothing stored. Re-run with --store to write to the database.")
        return

    obs_id = store(args, canonical, candidates, effective_docket)
    print(f"\nStored observation #{obs_id} with {len(candidates)} pending EEI candidate(s).")
    if effective_docket:
        print(f"  case identifier: {effective_docket}")
    print("Next: review/approve them in the workbench (Layer 3).")


if __name__ == "__main__":
    main()
