"""
sources.py — Source adapters for the fraud-taxonomy scraper.

Each adapter knows how to turn a public-record page (DoJ press releases, FTC
consumer alerts, FBI IC3, CISA advisories) into a list of *candidate* staging
entries — dicts that will be written to staging_entry for human review.

A candidate looks like:
    {
        "review_lane": "single" | "bulk",
        "provenance":  "<feed/source identity used for bulk trust-approval>",
        "source_url":  "<exact page URL>",
        "source_name": "<human label, e.g. 'US DoJ'>",
        "payload":     { ... structured proposal ... },
    }

Narrative finds (press releases, alerts) go to the SINGLE lane — they need
one-at-a-time human reading. List/feed data (e.g., indicator lists) would go
to the BULK lane keyed by provenance. None of these adapters invents facts;
they extract title, URL, date, and lead text, and hand them to a reviewer.

Adapters are deliberately conservative: they extract, they never auto-classify
a fraud type or write to live tables. Classification is the human's job at
review time.

To add a new source later: write a new adapter class with a `.parse(html, url)`
method returning candidates, and register it in ADAPTERS. No schema change.
"""

from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup


def _clean(text):
    return " ".join((text or "").split())


class BaseAdapter:
    #: human label shown in the review UI
    source_name = "Unknown"
    #: provenance string (used to group bulk batches; also tags single entries)
    provenance = "unknown"
    #: which review lane this source's output should go to
    review_lane = "single"

    def parse(self, html, url):
        raise NotImplementedError


class DoJPressReleaseListAdapter(BaseAdapter):
    """
    Parses a U.S. DoJ press-release LISTING page into candidate entries, one
    per linked release. Narrative -> single lane.

    The DoJ site structure changes over time; this adapter is intentionally
    defensive, looking for article/teaser blocks with a title link and date.
    """
    source_name = "US DoJ"
    provenance = "DoJ press releases"
    review_lane = "single"

    def parse(self, html, url):
        soup = BeautifulSoup(html, "html.parser")
        candidates = []

        # DoJ listing pages typically wrap each item in an <article> or a
        # teaser div; we try a few selectors and dedupe by resolved URL.
        seen = set()
        blocks = soup.select("article, .views-row, .teaser, li.usa-collection__item")
        if not blocks:
            # fall back to any anchor that looks like a press-release link
            blocks = soup.select("a[href*='/pr/'], a[href*='press-release']")

        for b in blocks:
            link = b if b.name == "a" else (b.find("a", href=True))
            if not link or not link.get("href"):
                continue
            href = urljoin(url, link["href"])
            if href in seen:
                continue
            seen.add(href)

            title = _clean(link.get_text())
            if not title or len(title) < 8:
                continue

            # try to find a nearby date and lead/summary
            date_text = None
            date_el = b.find("time") if hasattr(b, "find") else None
            if date_el:
                date_text = _clean(date_el.get_text()) or date_el.get("datetime")
            lead = None
            p = b.find("p") if hasattr(b, "find") else None
            if p:
                lead = _clean(p.get_text())

            candidates.append({
                "review_lane": self.review_lane,
                "provenance": self.provenance,
                "source_url": href,
                "source_name": self.source_name,
                "payload": {
                    "proposed": "observation",
                    "title": title,
                    "date_text": date_text,
                    "lead": lead,
                    "agency": "US DoJ",
                    "note": "Candidate from DoJ listing; reviewer to confirm fraud type(s) and extract details.",
                },
            })
        return candidates


class GenericGovAlertAdapter(BaseAdapter):
    """
    A conservative adapter for a SINGLE government alert/advisory page
    (FTC consumer alert, CISA advisory, IC3 PSA). Extracts the page title,
    publication date if present, and the first substantive paragraph as a lead.
    Narrative -> single lane.
    """
    source_name = "Gov advisory"
    provenance = "gov advisory"
    review_lane = "single"

    def __init__(self, source_name=None, provenance=None, agency=None):
        if source_name:
            self.source_name = source_name
        if provenance:
            self.provenance = provenance
        self.agency = agency or source_name or "gov"

    def parse(self, html, url):
        soup = BeautifulSoup(html, "html.parser")

        # title: prefer <h1>, then <title>
        h1 = soup.find("h1")
        title = _clean(h1.get_text()) if h1 else _clean(
            soup.title.get_text() if soup.title else ""
        )
        if not title:
            return []

        # date: first <time> or a meta published date
        date_text = None
        t = soup.find("time")
        if t:
            date_text = _clean(t.get_text()) or t.get("datetime")
        else:
            meta = soup.find("meta", attrs={"property": "article:published_time"})
            if meta and meta.get("content"):
                date_text = meta["content"]

        # lead: first paragraph with reasonable length inside main/article
        lead = None
        container = soup.find("main") or soup.find("article") or soup
        for p in container.find_all("p"):
            txt = _clean(p.get_text())
            if len(txt) >= 60:
                lead = txt
                break

        return [{
            "review_lane": self.review_lane,
            "provenance": self.provenance,
            "source_url": url,
            "source_name": self.source_name,
            "payload": {
                "proposed": "observation",
                "title": title,
                "date_text": date_text,
                "lead": lead,
                "agency": self.agency,
                "note": "Candidate from gov advisory; reviewer to confirm fraud type(s) and extract signals/selectors.",
            },
        }]


# Registry: extend this as you discover useful sources. No schema change needed.
ADAPTERS = {
    "doj_list": DoJPressReleaseListAdapter,
    "gov_alert": GenericGovAlertAdapter,
    "feed": None,  # set below after FeedAdapter is defined
}


class FeedAdapter(BaseAdapter):
    """
    Reads an RSS or Atom feed (the structured, programmatic-access format that
    government sites publish specifically for this purpose) and turns each item
    into a candidate. Far more reliable than scraping JavaScript-rendered HTML.

    Uses only the Python standard library (xml.etree) — no extra dependency.

    Known-good FTC feeds (current as of build):
      Press releases ........... https://www.ftc.gov/feeds/press-release.xml
      Consumer protection PR ... https://www.ftc.gov/feeds/press-release-consumer-protection.xml
      Consumer blog ............ https://www.consumer.ftc.gov/blog/gd-rss.xml

    Narrative items -> single lane.
    """
    source_name = "RSS/Atom feed"
    provenance = "feed"
    review_lane = "single"

    def __init__(self, source_name=None, provenance=None, agency=None):
        if source_name:
            self.source_name = source_name
        if provenance:
            self.provenance = provenance
        self.agency = agency or source_name or "feed"

    def parse(self, xml_text, url):
        import xml.etree.ElementTree as ET

        # Strip a leading BOM/whitespace that can trip the parser
        xml_text = xml_text.lstrip("\ufeff \t\r\n")
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        candidates = []

        # RSS 2.0: <rss><channel><item>...
        items = root.findall(".//item")
        if items:
            for it in items:
                title = _clean(_text(it.find("title")))
                link = _clean(_text(it.find("link")))
                date_text = _clean(_text(it.find("pubDate")))
                desc = _clean(_text(it.find("description")))
                if not title:
                    continue
                candidates.append(self._candidate(title, link or url, date_text, desc))
            return candidates

        # Atom: <feed><entry>... with namespace
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = root.findall(".//a:entry", ns)
        for e in entries:
            title = _clean(_text(e.find("a:title", ns)))
            link_el = e.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else url
            date_text = _clean(_text(e.find("a:updated", ns)) or _text(e.find("a:published", ns)))
            desc = _clean(_text(e.find("a:summary", ns)))
            if not title:
                continue
            candidates.append(self._candidate(title, link or url, date_text, desc))
        return candidates

    def _candidate(self, title, link, date_text, lead):
        return {
            "review_lane": self.review_lane,
            "provenance": self.provenance,
            "source_url": link,
            "source_name": self.source_name,
            "payload": {
                "proposed": "observation",
                "title": title,
                "date_text": date_text or None,
                "lead": lead or None,
                "agency": self.agency,
                "note": "Candidate from RSS/Atom feed; reviewer to confirm fraud type(s) and extract signals/selectors.",
            },
        }


def _text(el):
    return el.text if el is not None and el.text else ""


class AGListingAdapter(BaseAdapter):
    """
    Generic adapter for a state Attorney General news/press LISTING page that
    serves real server-side HTML. Extracts candidate links that look like news
    or press-release items, with nearby title text and any <time> date.

    Conservative by design: it pulls links + titles for human review, never
    auto-classifies a fraud type. Provenance is set per-source by the caller
    (the state_ag mode passes state + AG office).
    """
    source_name = "State AG"
    provenance = "state AG"
    review_lane = "single"

    #: URL path fragments that suggest an individual news/press item
    _ITEM_HINTS = ("news", "press", "release", "media", "article", "taking-action")

    def __init__(self, source_name=None, provenance=None, agency=None):
        if source_name:
            self.source_name = source_name
        if provenance:
            self.provenance = provenance
        self.agency = agency or source_name or "State AG"

    def parse(self, html, url):
        soup = BeautifulSoup(html, "html.parser")
        base = url
        seen = set()
        candidates = []

        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"])
            low = href.lower()
            # keep only links that look like individual news/press items on the
            # same host, and skip the listing/section root itself
            if not any(h in low for h in self._ITEM_HINTS):
                continue
            if urlparse(href).netloc != urlparse(base).netloc:
                continue
            if href.rstrip("/") == base.rstrip("/"):
                continue
            if href in seen:
                continue
            title = _clean(a.get_text())
            # require a real, sentence-like title to avoid nav/menu links
            if len(title) < 20 or " " not in title:
                continue
            seen.add(href)
            candidates.append({
                "review_lane": self.review_lane,
                "provenance": self.provenance,
                "source_url": href,
                "source_name": self.source_name,
                "payload": {
                    "proposed": "observation",
                    "title": title,
                    "date_text": None,
                    "lead": None,
                    "agency": self.agency,
                    "note": "Candidate from state AG listing; reviewer to confirm fraud relevance, type(s), and extract details.",
                },
            })
        return candidates


ADAPTERS["feed"] = FeedAdapter
ADAPTERS["ag_listing"] = AGListingAdapter
