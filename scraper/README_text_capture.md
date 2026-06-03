# text_capture.py — Capture, clean, extract case text

Turns a fraud case (from a URL, a saved HTML file, or pasted text) into clean
canonical text + extracted EEI candidates, ready for human review.

## The three input modes

```bash
# 1. Fetch a URL via the responsible fetcher (sanctioned sources only):
python3 text_capture.py --url https://www.ic3.gov/PSA/2026/PSA260527

# 2. Parse a local .html file you saved from your browser
#    (use this for bot-walled sources like DoJ/FTC/FBI — a human in a browser
#     can access what the automated scraper cannot):
python3 text_capture.py --file ~/Downloads/doj_release.html

# 3. Paste article text directly (copy from your browser, then Ctrl-D):
python3 text_capture.py --paste
```

All three: dry-run by default (prints canonical text + extracted EEIs, stores
nothing). Add `--show-text` to print the full cleaned text.

## Storing to the database

Add `--store` plus optional case-identity fields (migration 005):

```bash
python3 text_capture.py --file ~/Downloads/doj_release.html --store \
    --title "US v. Defendant — phantom Rolex scheme" \
    --agency "US DoJ" --jurisdiction "US" \
    --docket "1:23-cr-00456" --case-name "United States v. Defendant" \
    --court "N.D. Cal." --jurisdiction-level federal \
    --note "Same case as CA AG release 2026-05-20"
```

This creates one `observation` (with the captured text + case identity) and a
`pending` `eei_candidate` row per extracted EEI, for review in the workbench.

## How cleanup works (and its limits)

- **Tier 1 (high fidelity):** removes `<script>/<nav>/<header>/<footer>/<form>`
  etc. — structural site chrome.
- **Tier 2 (medium fidelity):** strips known boilerplate phrases (newsletter,
  translate disclaimer, skip-to-content...). Edit the `_BOILERPLATE` list to add more.
- **Tier 3 (NOT done here):** judging whether a `$50,000` is the loss or a bail
  amount is *pertinence*, which is the human reviewer's job. The extractor
  surfaces all candidates; the human decides which matter.

## The offset invariant

The text is **cleaned once**, then EEI offsets are computed against that cleaned
text, and that **same** text is stored as `observation.captured_text`. So the
stored text, the extracted offsets, and what the GUI will display are identical —
guaranteeing every highlight lands correctly. The script prints an
`OFFSET MISMATCH` flag if this is ever violated (it should never appear).

## Refinements (added after live DoJ testing)

- **"Related Content" truncation (Tier 1.5):** government press pages often append
  a sidebar of *other* press releases ("Related Content"). The cleanup truncates
  the captured text at that boundary, so amounts/EEIs from unrelated cases are not
  extracted. This is a structural cut at a reliable marker — not a pertinence
  guess. Markers are editable in `_TRUNCATE_MARKERS`.
- **Release-number capture:** if the page declares a "Press Release Number:" (DoJ
  convention), it's auto-detected and offered as the docket/case-id when you store
  with `--store` (your `--docket` always overrides). Captured from the full text
  *before* truncation so a boundary-adjacent number isn't lost.
