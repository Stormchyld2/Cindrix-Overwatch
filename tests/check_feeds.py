"""Fetches every real source from a CI machine and reports what happened. Run: python -m tests.check_feeds

Informational except for the two core government feeds, which must work. Also looks for the real feed
links on military and defense home pages so the source list can be pinned to addresses that exist.
"""

import re
import sys
import time
from urllib.parse import urljoin

from cindrix_overwatch import engine, feeds, sources

HOMES = ["https://www.defense.gov/", "https://www.navy.mil/", "https://www.af.mil/", "https://www.army.mil/",
         "https://www.marines.mil/", "https://www.spaceforce.mil/", "https://www.centcom.mil/",
         "https://www.eucom.mil/", "https://www.pacom.mil/", "https://www.africom.mil/",
         "https://www.northcom.mil/", "https://www.southcom.mil/", "https://www.nato.int/",
         "https://www.understandingwar.org/", "https://www.dvidshub.net/", "https://www.coastguard.dev/"]
FEED_RE = re.compile(r"""(?:href|src)=["']([^"']*(?:RSS\.ashx|\.rss|/rss[/?"']|\.atom|/feed[/?"'])[^"']*)["']""", re.I)
LINK_RE = re.compile(r"""<link[^>]+type=["']application/(?:rss|atom)\+xml["'][^>]*>""", re.I)
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.I)


def main():
    srcs = sources.nws_sources(["WV"]) + sources.BUILTIN + sources.trial_sources()
    bad_core = []
    print(f"{'source':16} {'result':10} items  note")
    for s in srcs:
        if "gdeltproject" in s["url"]:
            time.sleep(6)        # GDELT allows one request per five seconds
        status, text = engine.default_fetch(s["url"])
        if status != 200:
            res, n, note = f"HTTP {status}", "", (text or "")[:80]
        else:
            try:
                items = feeds.PARSERS[s["parser"]](text, s)
                res, n, note = "ok", len(items), (items[0].title[:70] if items else "(empty but valid)")
            except feeds.FeedError as e:
                res, n, note = "unreadable", "", str(e)[:80] + " | starts: " + text[:60].replace("\n", " ")
        print(f"{s['id']:16} {res:10} {n!s:5}  {note}")
        if s["id"] in ("usgs", "nws-wv") and res != "ok":
            bad_core.append(s["id"])
    print("\nFeed links found on home pages (use these to pin exact addresses):")
    for url in HOMES:
        status, text = engine.default_fetch(url)
        if status != 200:
            print(f"  {url}  -> HTTP {status}")
            continue
        found = []
        for tag in LINK_RE.findall(text):
            m = HREF_RE.search(tag)
            if m:
                found.append(urljoin(url, m.group(1)))
        found += [urljoin(url, h) for h in FEED_RE.findall(text)]
        uniq = list(dict.fromkeys(found))[:8]
        print(f"  {url}  -> {len(uniq)} link(s)")
        for u in uniq:
            print(f"      {u}")
    if bad_core:
        print("\nCore feeds failed:", bad_core)
        sys.exit(1)


if __name__ == "__main__":
    main()
