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
    _s("airforce", "US Air Force", "Military", "military", "official", "https://www.af.mil" + _dod(1)),
    _s("centcom", "US Central Command", "Military", "military", "official", "https://www.centcom.mil" + _dod(808)),
    _s("ukmod", "UK Ministry of Defence", "Military", "military", "official",
       "https://www.gov.uk/government/organisations/ministry-of-defence.atom"),
    # ----- world news and crisis reporting -----
    _s("bbc", "BBC World", "News", "news", "wire", "https://feeds.bbci.co.uk/news/world/rss.xml", every=20),
    _s("aljazeera", "Al Jazeera", "News", "news", "wire", "https://www.aljazeera.com/xml/rss/all.xml", every=20),
    _s("dw", "Deutsche Welle", "News", "news", "wire", "https://rss.dw.com/rdf/rss-en-world", every=30),
    _s("npr", "NPR World", "News", "news", "wire", "https://feeds.npr.org/1004/rss.xml", every=30),
    _s("un", "UN News", "News", "news", "official", "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
    _s("who", "WHO news", "Health", "health", "official",
       "https://www.who.int/rss-feeds/news-english.xml", every=120),
    _s("gdelt-conflict", "GDELT: conflict", "News", "conflict", "outlet",
       "https://api.gdeltproject.org/api/v2/doc/doc?query=%28airstrike%20OR%20missile%20OR%20shelling%20OR%20offensive%29%20sourcelang%3Aeng"
       "&mode=artlist&maxrecords=60&format=json&sort=datedesc&timespan=6h", "gdelt", 30),
    _s("gdelt-military", "GDELT: military", "News", "military", "outlet",
       "https://api.gdeltproject.org/api/v2/doc/doc?query=%28navy%20OR%20warship%20OR%20%22air%20force%22%20OR%20troops%20OR%20nato%29%20sourcelang%3Aeng"
       "&mode=artlist&maxrecords=60&format=json&sort=datedesc&timespan=6h", "gdelt", 30),
]


# Tried from a GitHub runner and not usable yet: the Navy and Indo-Pacific feed addresses returned nothing,
# EUCOM and several .mil home pages refuse data-centre addresses (HTTP 403), NATO's guessed address was 404.
# They may work from a home connection. Add them as custom feeds to try; DVIDS already carries all services.
CANDIDATES = [
    ("US Navy", "https://www.navy.mil" + _dod(1)),
    ("US European Command", "https://www.eucom.mil" + _dod(1)),
    ("US Indo-Pacific Command", "https://www.pacom.mil" + _dod(1)),
    ("ReliefWeb (answers HTTP 406 to automated requests)", "https://reliefweb.int/updates/rss.xml"),
]


# Early-warning candidates being tested from a real runner (see tests/check_feeds.py). Only ones that fetch and read
# correctly get promoted into BUILTIN. Each is (id, name, group, kind, trust, url).
TRIAL = [
    ("usni", "USNI News (fleet and carrier tracker)", "Military", "military", "outlet", "https://news.usni.org/feed"),
    ("stripes", "Stars and Stripes", "Military", "military", "outlet", "https://www.stripes.com/feeds/rss/"),
    ("defnews", "Defense News", "Military", "military", "outlet", "https://www.defensenews.com/arc/outboundfeeds/rss/"),
    ("breaking", "Breaking Defense", "Military", "military", "outlet", "https://breakingdefense.com/feed/"),
    ("twz", "The War Zone", "Military", "military", "outlet", "https://www.twz.com/feed"),
    ("milt", "Military Times", "Military", "military", "outlet",
     "https://www.militarytimes.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("isw", "Institute for the Study of War", "Conflict", "conflict", "outlet", "https://understandingwar.org/feed"),
    ("crisis", "Crisis Group (CrisisWatch)", "Conflict", "conflict", "outlet", "https://www.crisisgroup.org/rss"),
    ("kyiv", "Kyiv Independent", "Conflict", "conflict", "outlet", "https://kyivindependent.com/news-archive/rss/"),
    ("toi", "Times of Israel", "Conflict", "conflict", "outlet", "https://www.timesofisrael.com/feed/"),
    ("scmp", "South China Morning Post (Asia)", "News", "news", "outlet", "https://www.scmp.com/rss/91/feed"),
    ("taiwan", "Focus Taiwan", "News", "news", "wire", "https://focustaiwan.tw/rss/aall.xml"),
    ("japan", "Japan Times", "News", "news", "outlet", "https://www.japantimes.co.jp/feed/"),
    ("yonhap", "Yonhap (Korea)", "News", "news", "wire", "https://en.yna.co.kr/RSS/news.xml"),
    ("travel", "State Dept travel advisories", "Hazards", "news", "official", "https://travel.state.gov/_res/rss/TAsTWs.xml"),
    ("cisa", "CISA cyber advisories", "Hazards", "news", "official", "https://www.cisa.gov/cybersecurity-advisories/all.xml"),
    ("fema", "FEMA disaster declarations", "Hazards", "hazard", "official", "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries.rss"),
    ("ap", "AP top news", "News", "news", "wire", "https://feedx.net/rss/ap.xml"),
    ("cbs", "CBS World", "News", "news", "outlet", "https://www.cbsnews.com/latest/rss/world"),
    ("france24", "France 24", "News", "news", "outlet", "https://www.france24.com/en/rss"),
    ("tass", "TASS (Russian state view)", "News", "news", "outlet", "https://tass.com/rss/v2.xml"),
    ("xinhua", "Xinhua (Chinese state view)", "News", "news", "outlet", "http://www.xinhuanet.com/english/rss/worldrss.xml"),
]


def trial_sources():
    return [_s(i, n, g, k, t, u) for i, n, g, k, t, u in TRIAL]


def nws_sources(states):
    out = []
    for st in states:
        out.append(_s(f"nws-{st.lower()}", f"Weather alerts: {st}", "Home", "weather", "official",
                      f"https://api.weather.gov/alerts/active?area={st}", "nws", 10))
    return out


def valid_feed_url(url):
    """Custom feeds must be https and not a bare IP address. A .onion address may use http (Tor encrypts it)."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    host = p.hostname or ""
    if re.fullmatch(r"[a-z2-7]{56}\.onion", host.lower()):
        return p.scheme in ("http", "https")
    return p.scheme == "https" and "." in host and not re.fullmatch(r"[\d.]+", host) and ":" not in host


def custom_sources(entries):
    out = []
    for i, e in enumerate(entries or []):
        if not isinstance(e, dict) or not valid_feed_url(e.get("url")):
            continue
        kind = e.get("kind") if e.get("kind") in ("military", "conflict", "hazard", "health", "news") else "news"
        onion = bool(re.search(r"\.onion(?::|/|$)", urlparse(e["url"]).netloc.lower() + "/"))
        out.append(_s(f"custom-{i}", str(e.get("name") or "Custom feed")[:60], "Mine (Tor)" if onion else "Mine", kind,
                      "outlet", e["url"], "rss", 30, "custom", tor=onion))
    return out


def all_sources(settings):
    states = [s for s in settings.get("home_states", []) if isinstance(s, str) and len(s) == 2]
    disabled = set(settings.get("disabled", []))
    srcs = nws_sources(states) + BUILTIN + custom_sources(settings.get("custom_feeds", []))
    return [s for s in srcs if s["id"] not in disabled]


# Sites worth reading, with the onion address where the owner supplied one. The onion addresses below were pasted in by
# the owner (2026-11-04); they are checked for shape only until the Tor check in CI reaches them (tests/check_tor.py).
# 'home' is the normal website used to find the feed. Anything you add yourself is kept in your settings.
ONION_OUTLETS = [
    ("BBC News", "https://www.bbc.com/news", "news"),
    ("Deutsche Welle", "https://www.dw.com/en/", "news"),
    ("The Guardian", "https://www.theguardian.com/", "news"),
    ("ProPublica", "https://www.propublica.org/", "news"),
    ("The Intercept", "https://theintercept.com/", "news"),
    ("Bellingcat", "https://www.bellingcat.com/", "conflict"),
    ("Radio Free Europe / Radio Liberty", "https://www.rferl.org/", "news"),
    ("Voice of America", "https://www.voanews.com/", "news"),
    ("taz (Die Tageszeitung)", "https://taz.de/", "news"),
    ("The Associated Press", "https://apnews.com", "news"),
    ("Reuters", "https://reuters.com", "news"),
    ("Liveuamap", "https://liveuamap.com", "conflict"),
    ("U.S. European Command (EUCOM)", "https://eucom.mil", "military"),
    ("U.S. Department of Defense", "https://defense.gov", "military"),
    ("NOAA / National Weather Service", "https://weather.gov", "hazard"),
    ("USGS Earthquake Hazards", "https://usgs.gov", "hazard"),
    ("GDACS", "https://gdacs.org", "hazard"),
    ("Central Intelligence Agency (CIA)", "https://www.cia.gov/", "news"),
    ("Current Time TV", "https://www.currenttime.tv/", "news"),
    ("Radio Free Asia", "https://www.rfa.org/english/", "news"),
]

# Left out because they are not valid onion addresses (a current one is exactly 56 characters before .onion; these were
# 57, 55 and 55): CIA, Radio Free Asia, Voice of America. Paste the right ones from each site's own page.
SUPPLIED_ONIONS = {
    "BBC News": "https://bbcnewsd73hkzno2ini43t4gblxvycyac5aw4gnv7t2rccijh7745uqd.onion",
    "Deutsche Welle": "https://dwnewsgngmhlplxy6o2twtfgjnrnjxbegbwqx6wnotdhkzt562tszfid.onion",
    "The Guardian": "https://guardian2zotagl6tmjucg3lrhxdk4dw3lhbqnkvvkywawy3oqfoprid.onion",
    "The Intercept": "https://27m3p2uv7igmj6kvd4ql3cct5h3sdwrsajovkkndeufumzyfhlfev4qd.onion",
    "ProPublica": "https://p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion",
    "Radio Free Europe / Radio Liberty": "https://rferlo2zxgv23tct66v45s5mecftol5vod3hf4rqbipfp46fqu2q56ad.onion",
    "Current Time TV": "https://currtv242aqatxhyqfyh3mtq2ubzxz7crvj7aon3zccrnwatc5gugvqd.onion",
}
