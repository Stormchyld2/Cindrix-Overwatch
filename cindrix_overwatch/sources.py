"""The list of places Overwatch reads from. Public, official or openly published, no keys, no logins.

Each source has an id, a name, the group it shows under, the kind it produces, how much it can be trusted,
the parser, and how often to ask (minutes). Home weather sources are built from the home states.

The 'status' note is honest about what has been checked: 'checked' means a real fetch from a Windows
machine worked and was read correctly (see tests/check_feeds.py and the CI log); 'untested' has not been
fetched yet. A source that fails is shown as broken in the Sources tab and never stops the others.
"""

import re
from urllib.parse import urlparse

UA = "CindrixOverwatch/0.1 (+https://github.com/Stormchyld2/Cindrix-Overwatch)"


def _s(id, name, group, kind, trust, url, parser="rss", every=30, status="untested", **kw):
    d = dict(id=id, name=name, group=group, kind=kind, trust=trust, url=url, parser=parser, every=every,
             status=status)
    d.update(kw)
    return d


def _dod(site):
    return f"/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site={site}&max=15"


BUILTIN = [
    # ----- hazards: official data feeds -----
    _s("usgs", "USGS earthquakes", "Hazards", "hazard", "official",
       "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson", "usgs", 15),
    _s("eonet", "NASA natural events", "Hazards", "hazard", "official",
       "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=7", "eonet", 60),
    _s("gdacs", "GDACS disaster alerts", "Hazards", "hazard", "official", "https://www.gdacs.org/xml/rss.xml",
       "gdacs", 30),
    _s("swpc", "NOAA space weather", "Hazards", "space", "official",
       "https://services.swpc.noaa.gov/products/noaa-scales.json", "swpc", 30),
    # ----- military and defense: official releases -----
    _s("dvids", "DVIDS (all services)", "Military", "military", "official", "https://www.dvidshub.net/rss/news"),
    _s("defense", "Defense Department", "Military", "military", "official",
       "https://www.defense.gov" + _dod(945)),
    _s("navy", "US Navy", "Military", "military", "official", "https://www.navy.mil" + _dod(1)),
    _s("airforce", "US Air Force", "Military", "military", "official", "https://www.af.mil" + _dod(1)),
    _s("centcom", "US Central Command", "Military", "military", "official", "https://www.centcom.mil" + _dod(808)),
    _s("eucom", "US European Command", "Military", "military", "official", "https://www.eucom.mil" + _dod(1)),
    _s("indopacom", "US Indo-Pacific Command", "Military", "military", "official", "https://www.pacom.mil" + _dod(1)),
    _s("ukmod", "UK Ministry of Defence", "Military", "military", "official",
       "https://www.gov.uk/government/organisations/ministry-of-defence.atom"),
    _s("nato", "NATO", "Military", "military", "official", "https://www.nato.int/cps/en/natohq/news.rss"),
    # ----- world news and crisis reporting -----
    _s("bbc", "BBC World", "News", "news", "wire", "https://feeds.bbci.co.uk/news/world/rss.xml", every=20),
    _s("aljazeera", "Al Jazeera", "News", "news", "wire", "https://www.aljazeera.com/xml/rss/all.xml", every=20),
    _s("dw", "Deutsche Welle", "News", "news", "wire", "https://rss.dw.com/rdf/rss-en-world", every=30),
    _s("npr", "NPR World", "News", "news", "wire", "https://feeds.npr.org/1004/rss.xml", every=30),
    _s("un", "UN News", "News", "news", "official", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
    _s("reliefweb", "ReliefWeb", "News", "news", "official", "https://reliefweb.int/updates/rss.xml", every=60),
    _s("who", "WHO outbreak news", "Health", "health", "official",
       "https://www.who.int/feeds/entity/csr/don/en/rss.xml", every=120),
    _s("gdelt-conflict", "GDELT: conflict", "News", "conflict", "outlet",
       "https://api.gdeltproject.org/api/v2/doc/doc?query=%28airstrike%20OR%20missile%20OR%20shelling%20OR%20offensive%29%20sourcelang%3Aeng"
       "&mode=artlist&maxrecords=60&format=json&sort=datedesc&timespan=6h", "gdelt", 30),
    _s("gdelt-military", "GDELT: military", "News", "military", "outlet",
       "https://api.gdeltproject.org/api/v2/doc/doc?query=%28navy%20OR%20warship%20OR%20%22air%20force%22%20OR%20troops%20OR%20nato%29%20sourcelang%3Aeng"
       "&mode=artlist&maxrecords=60&format=json&sort=datedesc&timespan=6h", "gdelt", 30),
]


def nws_sources(states):
    out = []
    for st in states:
        out.append(_s(f"nws-{st.lower()}", f"Weather alerts: {st}", "Home", "weather", "official",
                      f"https://api.weather.gov/alerts/active?area={st}", "nws", 10))
    return out


def valid_feed_url(url):
    """Custom feeds must be https and not a bare IP address."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    host = p.hostname or ""
    return p.scheme == "https" and "." in host and not re.fullmatch(r"[\d.]+", host) and ":" not in host


def custom_sources(entries):
    out = []
    for i, e in enumerate(entries or []):
        if not isinstance(e, dict) or not valid_feed_url(e.get("url")):
            continue
        kind = e.get("kind") if e.get("kind") in ("military", "conflict", "hazard", "health", "news") else "news"
        out.append(_s(f"custom-{i}", str(e.get("name") or "Custom feed")[:60], "Mine", kind, "outlet", e["url"],
                      "rss", 30, "custom"))
    return out


def all_sources(settings):
    states = [s for s in settings.get("home_states", []) if isinstance(s, str) and len(s) == 2]
    disabled = set(settings.get("disabled", []))
    srcs = nws_sources(states) + BUILTIN + custom_sources(settings.get("custom_feeds", []))
    return [s for s in srcs if s["id"] not in disabled]
