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
    # ----- more of the Discord feed bot's list: defense analysis, world, cyber -----
    _s("wotr", "War on the Rocks", "Military", "military", "outlet", "https://warontherocks.com/feed/", "rss", 60),
    _s("taskpurpose", "Task & Purpose", "Military", "military", "outlet", "https://taskandpurpose.com/feed/"),
    _s("airspace", "Air & Space Forces Magazine", "Military", "military", "outlet", "https://www.airandspaceforces.com/feed/"),
    _s("guardian", "The Guardian World", "News", "news", "outlet", "https://www.theguardian.com/world/rss"),
    _s("cisa", "CISA cyber advisories", "Cyber", "cyber", "official", "https://www.cisa.gov/cybersecurity-advisories/all.xml", "rss", 60),
    _s("bleeping", "BleepingComputer", "Cyber", "cyber", "outlet", "https://www.bleepingcomputer.com/feed/"),
    _s("krebs", "Krebs on Security", "Cyber", "cyber", "outlet", "https://krebsonsecurity.com/feed/", "rss", 60),
    _s("thn", "The Hacker News", "Cyber", "cyber", "outlet", "https://feeds.feedburner.com/TheHackersNews"),
    # GDELT allows one request every five seconds per connection and blocks a connection for about 15 minutes when asked faster:
    # asked once an hour, last in every refresh, 15 seconds apart (see Controller.host_gaps)
    _s("gdelt-conflict", "GDELT: conflict", "News", "conflict", "outlet",
       "https://api.gdeltproject.org/api/v2/doc/doc?query=%28airstrike%20OR%20missile%20OR%20shelling%20OR%20offensive%29%20sourcelang%3Aeng"
       "&mode=artlist&maxrecords=60&format=json&sort=datedesc&timespan=6h", "gdelt", 60),
    _s("gdelt-military", "GDELT: military", "News", "military", "outlet",
       "https://api.gdeltproject.org/api/v2/doc/doc?query=%28navy%20OR%20warship%20OR%20%22air%20force%22%20OR%20troops%20OR%20nato%29%20sourcelang%3Aeng"
       "&mode=artlist&maxrecords=60&format=json&sort=datedesc&timespan=6h", "gdelt", 60),
    # ----- early warning: defense press, conflict analysis, advisories, Asia, hurricanes (each fetched and read from a real runner) -----
    _s("usgs-sig", "USGS significant quakes (week)", "Hazards", "hazard", "official",
       "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson", "usgs", 30, "checked"),
    _s("nhc", "NOAA National Hurricane Center (Atlantic)", "Hazards", "weather", "official",
       "https://www.nhc.noaa.gov/index-at.xml", "rss", 30, "checked"),
    _s("climate", "NOAA Climate.gov news", "Hazards", "news", "official",
       "https://www.climate.gov/news-features/feed.xml", "rss", 120, "checked"),
    _s("usni", "USNI News (fleet and carrier tracker)", "Military", "military", "outlet",
       "https://news.usni.org/feed", "rss", 30, "checked"),
    _s("defnews", "Defense News", "Military", "military", "outlet",
       "https://www.defensenews.com/arc/outboundfeeds/rss/", "rss", 30, "checked"),
    _s("breaking", "Breaking Defense", "Military", "military", "outlet",
       "https://breakingdefense.com/feed/", "rss", 30, "checked"),
    _s("twz", "The War Zone", "Military", "military", "outlet",
       "https://www.twz.com/feed", "rss", 30, "checked"),
    _s("milt", "Military Times", "Military", "military", "outlet",
       "https://www.militarytimes.com/arc/outboundfeeds/rss/?outputType=xml", "rss", 30, "checked"),
    _s("crisis", "Crisis Group (CrisisWatch)", "Conflict", "conflict", "outlet",
       "https://www.crisisgroup.org/rss", "rss", 60, "checked"),
    _s("kyiv", "Kyiv Independent", "Conflict", "conflict", "outlet",
       "https://kyivindependent.com/news-archive/rss/", "rss", 30, "checked"),
    _s("mee", "Middle East Eye", "Conflict", "conflict", "outlet",
       "https://www.middleeasteye.net/rss", "rss", 30, "checked"),
    _s("travel", "State Dept travel advisories", "Conflict", "conflict", "official",
       "https://travel.state.gov/_res/rss/TAsTWs.xml", "rss", 120, "checked"),
    _s("scmp", "South China Morning Post (Asia)", "News", "news", "outlet",
       "https://www.scmp.com/rss/91/feed", "rss", 30, "checked"),
    _s("japan", "Japan Times", "News", "news", "outlet",
       "https://www.japantimes.co.jp/feed/", "rss", 30, "checked"),
    _s("yonhap", "Yonhap (Korea)", "News", "news", "wire",
       "https://en.yna.co.kr/RSS/news.xml", "rss", 30, "checked"),
    _s("rfa", "Radio Free Asia", "News", "news", "outlet",
       "https://www.rfa.org/english/RSS", "rss", 30, "checked"),
    _s("rferl", "Radio Free Europe / Radio Liberty", "News", "news", "outlet",
       "https://www.rferl.org/api/", "rss", 30, "checked"),
    _s("voa", "Voice of America", "News", "news", "outlet",
       "https://www.voanews.com/api/", "rss", 30, "checked"),
    _s("cbs", "CBS World", "News", "news", "outlet",
       "https://www.cbsnews.com/latest/rss/world", "rss", 30, "checked"),
    _s("france24", "France 24", "News", "news", "outlet",
       "https://www.france24.com/en/rss", "rss", 30, "checked"),
    _s("tass", "TASS (Russian state view)", "News", "news", "outlet",
       "https://tass.com/rss/v2.xml", "rss", 30, "checked"),
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
    # Tried and refused or missing from a data-centre address (may work from a home connection): ISW (403), Times of Israel
    # (403), CISA (403), FEMA (404), Focus Taiwan (404), Stars and Stripes (404), Xinhua (http only).
    ("isw", "Institute for the Study of War", "Conflict", "conflict", "outlet", "https://understandingwar.org/feed"),
    ("toi", "Times of Israel", "Conflict", "conflict", "outlet", "https://www.timesofisrael.com/feed/"),
    ("stripes", "Stars and Stripes", "Military", "military", "outlet", "https://www.stripes.com/feeds/rss/"),
    # From the owner's second list: wrong or retired addresses (404 or "Invalid url"). The assistant can find the right ones.
    ("janes", "Janes defence headlines", "Military", "military", "outlet", "https://www.janes.com/feeds/news"),
    ("reuters", "Reuters World News", "News", "news", "wire",
     "https://www.reutersagency.com/feed/?best-topics=world-news&post_type=best"),
    ("nws-us", "NWS active alerts (all US)", "Hazards", "weather", "official", "https://alerts.weather.gov/cap/us.php?x=0"),
]


# The Intel page reads the same feeds the Discord bot posted, in the bot's four channels.
INTEL_CHANNELS = [("military", "Military", ("military",)), ("world", "World news", ("news", "conflict")),
                  ("cyber", "Cyber", ("cyber",)), ("alerts", "Alerts and weather", ("hazard", "weather", "space", "health"))]


def intel_channel(item):
    """Which Intel channel an item belongs to. Travel advisories sit with the alerts, as they did in the bot."""
    if item.source_id == "travel":
        return "alerts"
    for key, _, kinds in INTEL_CHANNELS:
        if item.kind in kinds:
            return key
    return "world"


def trial_sources():
    return [_s(e[0], e[1], e[2], e[3], e[4], e[5], e[6] if len(e) > 6 else "rss") for e in TRIAL]


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
        kind = e.get("kind") if e.get("kind") in ("military", "conflict", "hazard", "health", "news", "cyber") else "news"
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
    ("The New York Times", "https://www.nytimes.com/", "news"),
    ("Distributed Denial of Secrets", "https://ddosecrets.com/", "news"),
]

# Left out because they are not valid onion addresses (a current one is exactly 56 characters before .onion; these were
# 57, 55 and 55): CIA, Radio Free Asia, Voice of America. Paste the right ones from each site's own page.
# Reached through Tor from a CI runner on 2026-11-04 (the others did not answer then; a mirror can be down for a while).
REACHED_ONIONS = {"BBC News", "Deutsche Welle"}

SUPPLIED_ONIONS = {
    "BBC News": "https://bbcnewsd73hkzno2ini43t4gblxvycyac5aw4gnv7t2rccijh7745uqd.onion",
    "Deutsche Welle": "https://dwnewsgngmhlplxy6o2twtfgjnrnjxbegbwqx6wnotdhkzt562tszfid.onion",
    "The Guardian": "https://guardian2zotagl6tmjucg3lrhxdk4dw3lhbqnkvvkywawy3oqfoprid.onion",
    "The Intercept": "https://27m3p2uv7igmj6kvd4ql3cct5h3sdwrsajovkkndeufumzyfhlfev4qd.onion",
    "ProPublica": "https://p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion",
    "Radio Free Europe / Radio Liberty": "https://rferlo2zxgv23tct66v45s5mecftol5vod3hf4rqbipfp46fqu2q56ad.onion",
    "The New York Times": "https://nytimesn7cgmftshazwhfgzm37qxb44r64ytbb2dj3x62d2lljsciiyd.onion",
    "Distributed Denial of Secrets": "https://ddosxlvzzow7scc7egy75gpke54hgbg2frahxzaw6qq5osnzm7wistid.onion",
    "Current Time TV": "https://currtv242aqatxhyqfyh3mtq2ubzxz7crvj7aon3zccrnwatc5gugvqd.onion",
}
