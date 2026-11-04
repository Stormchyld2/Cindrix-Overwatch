"""Finds the feed behind a website address, and checks it really is a feed before it is added.

No searching the web: it reads the page you point at, follows the feed links the page itself advertises
(<link rel="alternate">), tries the usual feed paths, and keeps only addresses that parse as a real feed.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from . import feeds, sources
from .tor import is_onion_url

COMMON = ("/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/feeds/all.rss.xml",
          "/news/rss.xml", "/rss/all.xml")
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml", "text/xml", "application/xml")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower().split()
        if "alternate" in rel and a.get("type", "").lower() in FEED_TYPES and a.get("href"):
            self.found.append((a["href"], a.get("title", "")))


def normalize(text):
    """'bbc.com' -> 'https://bbc.com/'. Onion addresses default to http because that is how they are served."""
    t = (text or "").strip().strip("<>\"'")
    if not t:
        raise ValueError("Type a website address first.")
    if "://" not in t:
        t = ("http://" if re.match(r"^[a-z2-7]{56}\.onion", t.lower()) else "https://") + t
    p = urlparse(t)
    if p.scheme not in ("http", "https") or not p.hostname or "." not in p.hostname:
        raise ValueError("That does not look like a website address.")
    if not (sources.valid_feed_url(t) or is_onion_url(t)):
        raise ValueError("Use an https:// address with a website name (or a .onion address).")
    return t if p.path else t + "/"


def feed_title(text):
    try:
        root = feeds._xml_root(text)
    except feeds.FeedError:
        return ""
    for el in root.iter():
        if feeds._local(el.tag) == "title" and (el.text or "").strip():
            return " ".join(el.text.split())[:80]
    return ""


def check_feed(fetch, url):
    """Returns {'url','title','count'} if the address is a readable feed with at least one item, else None."""
    status, text = fetch(url)
    if status != 200 or not text:
        return None
    try:
        items = feeds.parse_rss(text, {"id": "probe", "name": "probe", "kind": "news", "trust": "outlet"}, 0)
    except feeds.FeedError:
        return None
    if not items:
        return None
    return {"url": url, "title": feed_title(text), "count": len(items)}


def find_feeds(fetch, address, say=None, limit=6):
    """Walks the steps and returns a list of verified feeds (best first). `say` receives plain-language progress."""
    say = say or (lambda m: None)
    url = normalize(address)
    say(f"Opening {urlparse(url).hostname}")
    status, text = fetch(url)
    if status != 200:
        raise ValueError("Could not open that site" + (f" (HTTP {status})." if status else f": {text}" if text else "."))
    direct = check_feed(lambda u: (status, text), url)
    if direct:
        say("That address is already a feed.")
        return [direct]
    p = _Links()
    try:
        p.feed(text[:300_000])
    except Exception:
        pass
    cands, seen = [], set()

    def add(u, why):
        u = urljoin(url, u)
        if u not in seen and urlparse(u).scheme in ("http", "https") and len(cands) < 14:
            seen.add(u)
            cands.append((u, why))
    for href, _ in p.found:
        add(href, "advertised by the page")
    say(f"The page advertises {len(p.found)} feed link(s)." if p.found else "The page does not advertise a feed. Trying usual places.")
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for path in COMMON:
        add(base + path, "usual place")
    good = []
    for u, why in cands:
        say("Checking " + u)
        ok = check_feed(fetch, u)
        if ok:
            ok["why"] = why
            good.append(ok)
            if len(good) >= limit:
                break
    if not good:
        raise ValueError("No readable feed found there. Some sites keep feeds off, or block automated readers.")
    return good


def guess_kind(url, title=""):
    s = (url + " " + title).lower()
    for kind, words in (("military", ("defense", "military", "army", "navy", "airforce", "centcom", ".mil")),
                        ("hazard", ("earthquake", "weather", "alert", "disaster", "volcano", "hurricane")),
                        ("health", ("health", "outbreak", "disease", "who.int", "cdc")),
                        ("conflict", ("war", "conflict", "crisis"))):
        if any(w in s for w in words):
            return kind
    return "news"
