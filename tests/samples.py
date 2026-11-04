"""Small hand-written payloads shaped like what each real source sends. Fictional content."""

import json
import time

NOW = 1_800_000_000.0


def rfc(ts):
    return time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(ts))


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def rss(items):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><description>{d}</description>"
                   f"<pubDate>{rfc(ts)}</pubDate></item>" for t, l, d, ts in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'


def atom(items):
    body = "".join(f'<entry><title>{t}</title><link href="{l}"/><updated>{iso(ts)}</updated>'
                   f"<summary>{d}</summary></entry>" for t, l, d, ts in items)
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'


NEWS_RSS = rss([
    ("Missile strike hits port city in Ukraine, dozens killed", "https://example.org/a1", "Officials said", NOW - 3600),
    ("Dozens killed after missile strike on Ukraine port city", "https://example.net/b1", "", NOW - 3000),
    ("Navy destroyer joins NATO exercise in the Baltic Sea", "https://example.org/a2", "", NOW - 7200),
    ("Local bakery wins award", "https://example.org/a3", "", NOW - 100),
])

USGS = json.dumps({"features": [
    {"id": "us1", "properties": {"mag": 6.2, "place": "30 km E of Somewhere, Japan", "time": int((NOW - 600) * 1000),
                                 "url": "https://earthquake.usgs.gov/e/us1"},
     "geometry": {"coordinates": [142.0, 38.0, 35.0]}},
    {"id": "us2", "properties": {"mag": 4.6, "place": "Near Charleston, West Virginia", "time": int((NOW - 900) * 1000),
                                 "url": "https://earthquake.usgs.gov/e/us2"},
     "geometry": {"coordinates": [-81.6, 38.3, 8.0]}},
    {"id": "bad", "properties": {"mag": None}, "geometry": {"coordinates": [0, 0]}},
]})

NWS = json.dumps({"features": [
    {"id": "urn:1", "properties": {"id": "urn:1", "event": "Winter Weather Advisory", "areaDesc": "Kanawha; Putnam",
                                   "severity": "Minor", "sent": iso(NOW - 1800), "headline": "Advisory until 6 PM",
                                   "geocode": {"UGC": ["WVZ035", "WVZ036"]}, "@id": "https://api.weather.gov/alerts/1"},
     "geometry": None},
    {"id": "urn:2", "properties": {"id": "urn:2", "event": "Tornado Warning", "areaDesc": "Knox", "severity": "Extreme",
                                   "sent": iso(NOW - 600), "geocode": {"UGC": ["TNC093"]}},
     "geometry": {"type": "Polygon", "coordinates": [[[-84, 35.9], [-83.8, 35.9], [-83.8, 36.1], [-84, 36.1]]]}},
]})

EONET = json.dumps({"events": [
    {"id": "EONET_1", "title": "Wildfire Example", "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_1",
     "categories": [{"id": "wildfires", "title": "Wildfires"}],
     "geometry": [{"date": iso(NOW - 7200), "type": "Point", "coordinates": [-120.0, 38.0]}]},
]})

GDACS = ('<?xml version="1.0"?><rss version="2.0" xmlns:georss="http://www.georss.org/georss" '
         'xmlns:gdacs="http://www.gdacs.org"><channel><item><title>Orange alert for tropical cyclone</title>'
         f'<link>https://www.gdacs.org/x</link><description>text</description><pubDate>{rfc(NOW - 5000)}</pubDate>'
         '<georss:point>15.5 120.1</georss:point><gdacs:alertlevel>Orange</gdacs:alertlevel></item></channel></rss>')

SWPC = json.dumps({"0": {"G": {"Scale": "1", "Text": "minor"}, "S": {"Scale": "0", "Text": "none"},
                         "R": {"Scale": "0", "Text": "none"}},
                   "1": {"G": {"Scale": "2", "Text": "moderate"}, "S": {"Scale": "0"}, "R": {"Scale": "1"}}})

GDELT = json.dumps({"articles": [
    {"url": "https://news.example.com/1", "title": "Airstrike reported near Gaza border crossing",
     "seendate": "20271231T120000Z", "domain": "news.example.com", "sourcecountry": "United States"},
]})

ATOM_MOD = atom([("Defence Secretary visits fleet in Baltic Sea", "https://www.gov.uk/x", "Visit", NOW - 4000)])

EVIL_XML = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
