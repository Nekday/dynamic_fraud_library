"""
fetcher.py — Responsible HTTP fetch layer for the fraud-taxonomy scraper.

Design commitments (these are the whole point — a scraper that an interviewer,
a lawyer, and a safeguards team would all be comfortable with):

  * Respects robots.txt for every host, every time.
  * Honors each site's declared Crawl-delay (falling back to a polite default).
  * Detects and refuses bot-challenge / interstitial pages (Cloudflare, Akamai)
    rather than treating a challenge as if it were real content.
  * Identifies itself honestly with a descriptive User-Agent and contact note.
  * Only fetches over HTTPS.
  * Targets public-record sources. It is NOT a general-purpose crawler and
    deliberately has no "follow every link" mode.

Nothing here writes to the database. Fetching and parsing are separate from
staging, which is itself separate from the human-reviewed promotion to live
tables. Defense in depth against accidentally ingesting junk.

Install (on macOS):  pip install requests beautifulsoup4
"""

import time
import urllib.robotparser
from urllib.parse import urlparse
import requests

# Honest, identifiable agent. Replace the contact with your own before real use.
USER_AGENT = (
    "FraudTaxonomyResearchBot/0.1 "
    "(+local research project; contact: your-email@email.com)"
)

DEFAULT_MIN_INTERVAL = 2.0   # seconds between requests to the same host
MAX_CRAWL_DELAY = 30.0       # cap: don't honor absurd delays that would hang us
REQUEST_TIMEOUT = 20         # seconds


class FetchError(Exception):
    """Raised when a fetch is disallowed, blocked, or fails."""


class ChallengeDetected(FetchError):
    """Raised specifically when a response is a bot-challenge/interstitial page.

    Separate from FetchError so callers (e.g. --probe mode) can distinguish
    'the site actively gates bots' from 'robots disallowed' or 'network error'.
    """


# Signatures of known bot-challenge / interstitial pages. If any appears in a
# response body, we treat the response as a wall — NOT as content — and refuse.
# We never attempt to solve or bypass these challenges.
_CHALLENGE_SIGNATURES = (
    # Cloudflare managed challenge / "Just a moment..."
    "just a moment...",
    "challenges.cloudflare.com",
    "_cf_chl_opt",
    "cf-chl",
    "enable javascript and cookies to continue",
    "/cdn-cgi/challenge-platform",
    # Akamai bot manager / interstitial
    "abusive automated request",
    "bm-verify",
    "/_sec/verify",
    "doj-interstitial",
    "apology_objects/interstitial",
    "the request resembles an abusive automated request",
)


def looks_like_challenge(body):
    """Return a short label if the body looks like a bot-challenge page, else None."""
    if not body:
        return None
    low = body.lower()
    for sig in _CHALLENGE_SIGNATURES:
        if sig in low:
            if "cloudflare" in low or "_cf_chl" in low or "just a moment" in low:
                return "cloudflare"
            if "akamai" in low or "bm-verify" in low or "abusive automated" in low or "interstitial" in low:
                return "akamai"
            return "challenge"
    return None


class ResponsibleFetcher:
    """
    A polite, robots-respecting fetcher. One instance can be reused across a
    run; it tracks per-host robots rules, crawl-delays, and last-request times.
    """

    def __init__(self, min_interval=DEFAULT_MIN_INTERVAL, user_agent=USER_AGENT):
        self.default_min_interval = min_interval
        self.user_agent = user_agent
        self._robots = {}          # host -> RobotFileParser (or None if unreadable)
        self._crawl_delay = {}     # host -> float seconds (resolved once per host)
        self._last_request = {}    # host -> timestamp
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    # ---- robots.txt ----
    def _robots_for(self, url):
        host = urlparse(url).netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
            try:
                rp.set_url(robots_url)
                rp.read()
            except Exception:
                rp = None
            self._robots[host] = rp
        return self._robots[host]

    def allowed(self, url):
        """True if robots.txt permits our agent to fetch this URL."""
        rp = self._robots_for(url)
        if rp is None:
            # Couldn't read robots; cautious-allow (callers restrict to vetted
            # sources anyway, and challenge-detection is a second line of defense).
            return True
        return rp.can_fetch(self.user_agent, url)

    def crawl_delay_for(self, url):
        """
        Resolve the crawl delay for this host: the site's declared Crawl-delay
        if present (capped at MAX_CRAWL_DELAY), otherwise our polite default.
        """
        host = urlparse(url).netloc
        if host not in self._crawl_delay:
            delay = self.default_min_interval
            rp = self._robots_for(url)
            if rp is not None:
                try:
                    # crawl_delay() returns the value for our UA (or *), or None
                    declared = rp.crawl_delay(self.user_agent)
                    if declared is not None:
                        delay = min(float(declared), MAX_CRAWL_DELAY)
                except Exception:
                    pass
            self._crawl_delay[host] = max(delay, self.default_min_interval)
        return self._crawl_delay[host]

    # ---- rate limiting ----
    def _throttle(self, url):
        host = urlparse(url).netloc
        interval = self.crawl_delay_for(url)
        last = self._last_request.get(host)
        if last is not None:
            elapsed = time.time() - last
            if elapsed < interval:
                time.sleep(interval - elapsed)
        self._last_request[host] = time.time()

    # ---- fetch ----
    def get(self, url):
        """
        Fetch a URL responsibly. Raises:
          * FetchError       — non-HTTPS, robots-disallowed, or HTTP/network error
          * ChallengeDetected — response is a bot-challenge/interstitial page
        Returns the response text only when it is genuine content.
        """
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise FetchError(f"Refusing non-HTTPS URL: {url}")
        if not self.allowed(url):
            raise FetchError(f"Blocked by robots.txt: {url}")
        self._throttle(url)
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise FetchError(f"Fetch failed for {url}: {e}") from e

        body = resp.text
        kind = looks_like_challenge(body)
        if kind:
            raise ChallengeDetected(
                f"Bot-challenge page detected ({kind}) at {url}; refusing to treat "
                f"as content and not attempting to bypass."
            )
        return body
