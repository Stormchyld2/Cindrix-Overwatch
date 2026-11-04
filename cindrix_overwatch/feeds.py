"""Turns what each source sends into Items. Pure functions: text in, items out, no network.

A parser never trusts the data: bad entries are skipped, and a document that is not what the source
should send raises FeedError so the source shows as broken instead of silently empty.
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

from . import geo
from .model import Item


class FeedError(Exception):
    pass


def _strip_html(s):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_time(text, default=None):
    """Handles RFC 822 (RSS), ISO 8601 (Atom, JSON) and GDELT's 20261104T041500Z. Falls back to default."""
    if not text:
        return default
    text = str(text).strip()
    try:
        return parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?", text)
    if m:
        return datetime(*map(int, m.groups()), tzinfo=timezone.utc).timestamp()
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        return default


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _xml_root(text):
    # Refuse DTDs and entities outright: that closes the "billion laughs" style attacks on the stdlib parser.
    head = text[:4000].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in text[:20000].upper():
        raise FeedError("The feed contained a DTD, which Overwatch refuses to read.")
    try:
        return ET.fromstring(text.lstrip("﻿").strip())
    except ET.ParseError as e:
        raise FeedError(f"Not a readable feed ({e}).")


def _child_text(el, *names):
    for c in el:
        if _local(c.tag) in names and (c.text or "").strip():
            return c.text.strip()
    return ""


def _geo_point(el):
    """georss:point 'lat lon', or geo:lat / geo:long."""
    lat = lon = None
    for c in el.iter():
        n = _local(c.tag)
        if n == "point" and c.text and len(c.text.split()) == 2:
            a, b = c.text.split()
            lat, lon = _num(a), _num(b)
        elif n == "lat":
            lat = _num(c.text)
        elif n in ("long", "lon"):
            lon = _num(c.text)
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None, None


def parse_rss(text, src, now=None):
    """RSS 2.0, RSS 1.0 (RDF) and Atom."""
    now = now or time.time()
    root = _xml_root(text)
    entries = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    if not entries and _local(root.tag) not in ("rss", "feed", "RDF", "rdf"):
        raise FeedError("This is not an RSS or Atom feed.")
    out = []
    for e in entries[:60]:
        title = _strip_html(_child_text(e, "title"))
        if not title:
            continue
        link = _child_text(e, "link")
        if not link:
            for c in e:
                if _local(c.tag) == "link" and c.get("href"):
                    link = c.get("href")
                    break
        if link and not link.lower().startswith(("http://", "https://")):
            link = ""
        summary = _strip_html(_child_text(e, "description", "summary", "content", "encoded"))
        ts = parse_time(_child_text(e, "pubDate", "published", "updated", "date"), now)
        lat, lon = _geo_point(e)
        out.append(_finish(Item(src["id"], src["name"], src["kind"], src["trust"], title, link, summary, ts,
                                lat, lon), src))
    return out


def _finish(item, src):
    """Pins an item that has no coordinates by looking for a place in its headline, and notes home states."""
    blob = item.title + " " + item.summary
    if not item.pinned:
        found = geo.find_place(item.title) or geo.find_place(item.summary)
        if found:
            item.place, item.lat, item.lon = found
    item.states = sorted(set(item.states) | set(geo.find_states(blob)))
    return item


def parse_usgs(text, src, now=None):
    try:
        data = json.loads(text)
        feats = data["features"]
    except (ValueError, KeyError, TypeError):
        raise FeedError("Not a USGS earthquake feed.")
    out = []
    for f in feats[:200]:
        try:
            p, c = f["properties"], f["geometry"]["coordinates"]
            mag = _num(p.get("mag"))
            if mag is None:
                continue
            sev = 3 if mag >= 7 else 2 if mag >= 6 else 1 if mag >= 5 else 0
            title = f"M{mag:.1f} earthquake, {p.get('place') or 'unknown place'}"
            out.append(Item(src["id"], src["name"], "hazard", "official", title, p.get("url") or "",
                            f"Depth {c[2]:.0f} km." if len(c) > 2 and c[2] is not None else "",
                            (p.get("time") or 0) / 1000.0, c[1], c[0], p.get("place") or "", sev,
                            uid=f"usgs-{f.get('id')}"))
        except (KeyError, TypeError, IndexError):
            continue
    return out


_NWS_SEV = {"Minor": 1, "Moderate": 1, "Severe": 2, "Extreme": 3}


def _centroid(geom):
    try:
        if geom["type"] == "Polygon":
            ring = geom["coordinates"][0]
        elif geom["type"] == "MultiPolygon":
            ring = geom["coordinates"][0][0]
        else:
            return None, None
        return sum(p[1] for p in ring) / len(ring), sum(p[0] for p in ring) / len(ring)
    except (KeyError, TypeError, IndexError, ZeroDivisionError):
        return None, None


def parse_nws(text, src, now=None):
    try:
        feats = json.loads(text)["features"]
    except (ValueError, KeyError, TypeError):
        raise FeedError("Not a National Weather Service alert feed.")
    out = []
    for f in feats[:150]:
        try:
            p = f["properties"]
            event = p.get("event") or "Weather alert"
            area = p.get("areaDesc") or ""
            sev = _NWS_SEV.get(p.get("severity"), 0)
            if "Warning" in event:
                sev = max(sev, 2)
            states = sorted({u[:2] for u in (p.get("geocode") or {}).get("UGC", []) if len(u) >= 2 and u[:2] in geo.STATES})
            lat, lon = _centroid(f.get("geometry"))
            if lat is None and states:
                lat, lon = geo.STATES[states[0]][1:]
            out.append(Item(src["id"], src["name"], "weather", "official", f"{event}: {area[:120]}",
                            p.get("@id") or f.get("id") or "", p.get("headline") or "",
                            parse_time(p.get("sent") or p.get("effective"), now), lat, lon, area[:80], sev, states,
                            uid=f"nws-{f.get('id') or p.get('id')}"))
        except (KeyError, TypeError, AttributeError):
            continue
    return out


def parse_eonet(text, src, now=None):
    try:
        events = json.loads(text)["events"]
    except (ValueError, KeyError, TypeError):
        raise FeedError("Not a NASA EONET feed.")
    out = []
    for e in events[:100]:
        try:
            geom = e["geometry"][-1]
            coords = geom["coordinates"]
            if geom.get("type") != "Point":
                continue
            cat = (e.get("categories") or [{}])[0].get("title", "Event")
            sev = 2 if cat in ("Volcanoes", "Severe Storms") else 1
            out.append(Item(src["id"], src["name"], "hazard", "official", f"{cat}: {e['title']}",
                            (e.get("sources") or [{}])[0].get("url") or e.get("link") or "", "",
                            parse_time(geom.get("date"), now), coords[1], coords[0], "", sev,
                            uid=f"eonet-{e.get('id')}"))
        except (KeyError, TypeError, IndexError):
            continue
    return out


_GDACS_SEV = {"red": 3, "orange": 2, "green": 0}


def parse_gdacs(text, src, now=None):
    root = _xml_root(text)
    out = []
    for e in root.iter():
        if _local(e.tag) != "item":
            continue
        title = _strip_html(_child_text(e, "title"))
        if not title:
            continue
        level = _child_text(e, "alertlevel").lower()
        lat, lon = _geo_point(e)
        out.append(Item(src["id"], src["name"], "hazard", "official", title, _child_text(e, "link"),
                        _strip_html(_child_text(e, "description")),
                        parse_time(_child_text(e, "pubDate"), now), lat, lon, "", _GDACS_SEV.get(level, 1)))
    if not out and _local(root.tag) != "rss":
        raise FeedError("Not a GDACS feed.")
    return out


def parse_swpc(text, src, now=None):
    """NOAA space-weather scales: geomagnetic storms (G), solar radiation (S), radio blackouts (R)."""
    try:
        data = json.loads(text)
        cur, fc = data["0"], data.get("1", {})
    except (ValueError, KeyError, TypeError, AttributeError):
        raise FeedError("Not a NOAA space-weather scales feed.")
    names = {"G": "Geomagnetic storm", "S": "Solar radiation storm", "R": "Radio blackout"}
    out = []
    for key, label in names.items():
        for when, block in (("now", cur), ("forecast", fc)):
            try:
                scale = int(block[key]["Scale"])
            except (KeyError, TypeError, ValueError):
                continue
            if scale >= 1:
                sev = 1 if scale == 1 else 2 if scale <= 3 else 3
                title = f"{label}: {key}{scale} ({'in progress' if when == 'now' else 'forecast, next day'})"
                out.append(Item(src["id"], src["name"], "space", "official", title,
                                "https://www.swpc.noaa.gov/", block[key].get("Text") or "", now or time.time(),
                                severity=sev, uid=f"swpc-{key}-{when}-{scale}"))
    return out


def parse_gdelt(text, src, now=None):
    try:
        arts = json.loads(text).get("articles", [])
    except (ValueError, AttributeError):
        # GDELT answers in plain text when a query is rejected or rate limited.
        raise FeedError("GDELT did not send a list of articles.")
    out = []
    for a in arts[:75]:
        try:
            title = a["title"]
            out.append(_finish(Item(src["id"], src["name"], src["kind"], "outlet", title, a["url"],
                                    a.get("domain", ""), parse_time(a.get("seendate"), now)), src))
        except (KeyError, TypeError):
            continue
    return out


PARSERS = {"rss": parse_rss, "usgs": parse_usgs, "nws": parse_nws, "eonet": parse_eonet, "gdacs": parse_gdacs,
           "swpc": parse_swpc, "gdelt": parse_gdelt}
