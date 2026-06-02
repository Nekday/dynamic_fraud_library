"""
fraud_filter.py — Layered fraud-relevance filter for scraped candidates.

A state Attorney General publishes news on antitrust, environment, civil rights,
consumer protection, and much more. Only some is fraud/scam relevant. This filter
keeps the review queue focused on likely-fraud items, with a selectable level
that trades precision for recall:

    Level 0 : OFF — keep everything (no filtering)
    Level 1 : just "fraud"                         (highest precision)
    Level 2 : Level 1 + general fraud legal terms  (scheme, defraud, false
              statements, material misrepresentation, ...)
    Level 3 : Level 2 + all named fraud typologies (romance scam, pig butchering,
              BEC, elder fraud, phishing, identity theft, ...)  (highest recall)

Matching is case-insensitive, on the title plus the lead/summary when present.
Every kept candidate is tagged with the exact keywords that matched (stored in
payload['matched_keywords']) — an evidence trail for the reviewer and useful
signal for future classifier training.

The keyword lists are plain Python below so you can edit them freely; no code
logic needs to change to add a term.
"""

# Level 1 — the single strongest signal
LEVEL_1 = [
    "fraud",
]

# Level 2 — general fraud legal/conduct terms (added on top of Level 1)
LEVEL_2_ADtl = [
    "defraud",
    "scheme",
    "false statements",
    "material misrepresentation",
    "misrepresentation",
    "embezzle",
    "money laundering",
    "deceptive",
    "deception",
    "ponzi",
]

# Level 3 — named fraud/scam typologies (added on top of Level 2)
LEVEL_3_ADtl = [
    "scam",
    "romance scam",
    "pig butchering",
    "pig-butchering",
    "business email compromise",
    "bec",
    "elder fraud",
    "elder abuse",
    "investment fraud",
    "crypto",
    "cryptocurrency",
    "phishing",
    "smishing",
    "vishing",
    "identity theft",
    "gift card",
    "robocall",
    "imposter",
    "impostor",
    "impersonation",
    "advance fee",
    "advance-fee",
    "lottery scam",
    "sweepstakes",
    "tech support scam",
    "grandparent scam",
    "wire fraud",
    "mail fraud",
    "telemarketing",
    "charity scam",
    "ate fraud",            # account takeover (rare literal; kept loose)
    "account takeover",
]


def keywords_for_level(level):
    """Return the active keyword list for a given level (1, 2, or 3)."""
    if level <= 0:
        return []
    kws = list(LEVEL_1)
    if level >= 2:
        kws += LEVEL_2_ADtl
    if level >= 3:
        kws += LEVEL_3_ADtl
    # de-dupe while preserving order
    seen = set()
    out = []
    for k in kws:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            out.append(kl)
    return out


def match_keywords(text, level):
    """Return the sorted list of distinct keywords from `level` found in `text`."""
    if not text:
        return []
    low = text.lower()
    hits = []
    for kw in keywords_for_level(level):
        if kw in low:
            hits.append(kw)
    # collapse obvious substring overlaps (e.g. 'fraud' inside 'wire fraud')
    # keep the longer, more specific phrases plus standalone 'fraud' if present
    return sorted(set(hits))


def filter_candidates(candidates, level):
    """
    Given a list of candidate dicts, return (kept, dropped_count).
    Level 0 keeps everything (no tagging). Levels 1-3 keep only candidates whose
    title+lead match at least one active keyword, tagging each with the matches.
    """
    if level <= 0:
        return candidates, 0

    kept = []
    dropped = 0
    for c in candidates:
        p = c.get("payload", {})
        haystack = " ".join(filter(None, [p.get("title", ""), p.get("lead", "")]))
        hits = match_keywords(haystack, level)
        if hits:
            p["matched_keywords"] = hits
            p["filter_level"] = level
            c["payload"] = p
            kept.append(c)
        else:
            dropped += 1
    return kept, dropped
