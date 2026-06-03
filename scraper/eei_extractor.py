"""
eei_extractor.py — Deterministic EEI (Essential Element of Information) extractor.

Scans captured case text with regex and returns candidate EEIs with their
character offsets, so the workbench GUI can highlight them in the stored copy
and the reviewer can approve/reject each.

First build (minimal, refinable): email, phone, url, amount.
Add more types by adding (classifier_type, compiled_regex) pairs to PATTERNS.

Each candidate is a dict:
    {
        "classifier_type": "email" | "phone" | "url" | "amount",
        "eei_class":       "selector",          # deterministic types are selectors
        "matched_value":   "<the matched string>",
        "highlight_text":  "<same string, for the highlight span>",
        "start_offset":    <int>,
        "end_offset":      <int>,
        "origin":          "regex",
    }

Offsets are 0-based indices into the exact text passed in, so they map directly
to the stored observation.captured_text.
"""

import re

# --- Patterns. Kept conservative to favor precision over recall. ---

# Email: standard, avoids trailing punctuation.
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# URL: http(s) only (we store HTTPS sources; http may appear in case text).
_URL = re.compile(
    r"\bhttps?://[^\s<>\"')]+",
    re.IGNORECASE,
)

# US phone: (123) 456-7890 | 123-456-7890 | 123.456.7890 | +1 123 456 7890
_PHONE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"
)

# Dollar amount: $4,000,000 | $1.5 million | $250 | $12.5 billion
_AMOUNT = re.compile(
    r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s?(?:million|billion|thousand|m|bn|k))?",
    re.IGNORECASE,
)

PATTERNS = [
    ("email", _EMAIL),
    ("url", _URL),
    ("phone", _PHONE),
    ("amount", _AMOUNT),
]


def _overlaps(a_start, a_end, spans):
    """True if [a_start,a_end) overlaps any (s,e) already taken."""
    for s, e in spans:
        if a_start < e and s < a_end:
            return True
    return False


def extract(text):
    """
    Return a list of deterministic EEI candidate dicts found in `text`,
    ordered by start_offset. Overlapping matches are resolved by precedence
    (earlier pattern in PATTERNS wins) so e.g. a URL containing digits is not
    also reported as a phone number.
    """
    if not text:
        return []

    taken = []          # list of (start,end) already claimed
    candidates = []

    for classifier_type, pattern in PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            value = m.group(0).strip()
            # recompute end if we stripped trailing whitespace
            end = start + len(m.group(0).rstrip())
            if not value:
                continue
            if _overlaps(start, end, taken):
                continue
            taken.append((start, end))
            candidates.append({
                "classifier_type": classifier_type,
                "eei_class": "selector",
                "matched_value": value,
                "highlight_text": value,
                "start_offset": start,
                "end_offset": end,
                "origin": "regex",
            })

    candidates.sort(key=lambda c: c["start_offset"])
    return candidates


if __name__ == "__main__":
    # quick self-demo
    sample = (
        "Victims were told to wire $4,000,000 to an account, then contact "
        "scammer@fraud.biz or call (415) 555-0142. A fake site at "
        "https://totally-legit-invest.example/login collected logins. "
        "Losses exceeded $12.5 million."
    )
    for c in extract(sample):
        print(f"{c['classifier_type']:8} [{c['start_offset']:>3}-{c['end_offset']:<3}] {c['matched_value']}")
