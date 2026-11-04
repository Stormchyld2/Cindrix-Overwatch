"""CI only: runs the feed assistant against sites whose feed addresses were wrong, and tries the addresses people supplied."""
from cindrix_overwatch import discover, engine

SITES = ["https://www.rferl.org/rssfeeds", "https://www.rferl.org/", "https://www.voanews.com/rssfeeds",
         "https://www.voanews.com/", "https://www.reuters.com/", "https://www.janes.com/", "https://www.climate.gov/",
         "https://www.cisa.gov/", "https://www.timesofisrael.com/", "https://www.understandingwar.org/"]
DIRECT = ["https://www.climate.gov/news-features/feed.xml",
          "https://www.reutersagency.com/feed/?best-topics=world-news&post_type=best",
          "https://www.rferl.org/api/z-pqpiev-q"]
for u in DIRECT:
    st, txt = engine.default_fetch(u)
    r = discover.check_feed(engine.default_fetch, u)
    print("DIRECT", u, "->", st, "feed ok" if r else "not a feed", (r or {}).get("count", ""), flush=True)
for site in SITES:
    try:
        got = discover.find_feeds(engine.default_fetch, site)
        print("ASSIST", site, "->", [(g["url"], g["count"]) for g in got[:3]], flush=True)
    except ValueError as e:
        print("ASSIST", site, "-> none:", str(e)[:90], flush=True)
