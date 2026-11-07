"""The Overwatch brain with no window code: fetches sources, keeps history, answers what the screen asks.

Network access goes through one injectable function, so tests run without the internet.
"""

import gzip
import io
import json
import os
import time
import urllib.error
import threading
import urllib.request
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

from . import ai, cameras, discover, feeds, geo, scoring, sources, tor
from .store import Store

MAX_BYTES = 5_000_000
KEEP_DAYS = 30
DEFAULT_SETTINGS = {"home_states": ["WV", "TN"], "custom_feeds": [], "disabled": [], "auto_minutes": 15,
                    "onion_addresses": {}, "my_outlets": [], "cameras": [], "watchtower": {}, "link": {}, "ai_root": "", "ai_enabled": False,
                    "ai_engine": "", "ai_model": "auto", "auto_translate": True, "ai_pins": True, "ai_focus": True, "ai_instructions": ""}


ACCEPT = "application/rss+xml, application/atom+xml, application/xml, application/json, text/xml, */*;q=0.8"
ACCEPT_BY_HOST = {"api.weather.gov": "application/geo+json"}      # otherwise it answers in Atom


def _was_reset(e):
    """True for 'connection forcibly closed' style errors (Windows 10054), which are usually worth one more try."""
    r = getattr(e, "reason", e)
    return isinstance(r, ConnectionError) or getattr(r, "winerror", None) in (10053, 10054) or getattr(r, "errno", None) in (104,)


def default_fetch(url, timeout=25):
    """Returns (status, text). Only https is allowed, including after redirects. Gzip is unpacked.
    A connection that is reset by the other side is tried once more after a short pause."""
    if not url.lower().startswith("https://"):
        return 0, ""
    accept = ACCEPT_BY_HOST.get(urlparse(url).hostname, ACCEPT)
    for attempt in (0, 1):
        req = urllib.request.Request(url, headers={"User-Agent": sources.UA, "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if not r.geturl().lower().startswith("https://"):
                    return 0, ""
                raw = r.read(MAX_BYTES)
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(MAX_BYTES)
                return r.status, raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except (urllib.error.URLError, OSError, TimeoutError, ValueError, EOFError) as e:
            if attempt == 0 and _was_reset(e):
                time.sleep(1.5)
                continue
            return 0, str(e)[:120]
    return 0, ""


class Controller:
    def __init__(self, root, fetch=None, now=time.time, tor_link=None):
        os.makedirs(root, exist_ok=True)
        self.tor = tor_link or tor.TorLink(root)
        self.ai = ai.AiService(self)
        self.root, self.now = root, now
        self.fetch = fetch or self._routed_fetch
        self.settings_path = os.path.join(root, "settings.json")
        self.store = Store(os.path.join(root, "overwatch.db"))
        self.settings = self._load_settings()
        # GDELT allows about one request every five seconds, so asks to that host are spaced out.
        self.host_gaps = {"api.gdeltproject.org": 15.0}
        self._host_next, self._host_lock = {}, threading.Lock()

    def _throttle(self, url):
        host = urlparse(url).hostname
        gap = self.host_gaps.get(host)
        if not gap:
            return
        with self._host_lock:
            t = time.monotonic()
            start = max(t, self._host_next.get(host, 0))
            self._host_next[host] = start + gap
        if start > t:
            time.sleep(start - t)

    def _routed_fetch(self, url):
        """Onion addresses go through Tor and nothing else; everything else is a normal https fetch."""
        if tor.is_onion_url(url):
            return self.tor.fetch(url)
        return default_fetch(url)

    def onion_location(self, url):
        """Asks a normal website for its official onion address (its Onion-Location header). Returns '' if none."""
        req = urllib.request.Request(url, headers={"User-Agent": sources.UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                loc = (r.headers.get("Onion-Location") or "").strip()
        except (urllib.error.URLError, OSError, ValueError):
            return ""
        return loc if tor.is_onion_url(loc) else ""

    def read_page(self, url, use_tor=True):
        """Raw page text for the reader. Onion addresses always use Tor; others use it when asked and available."""
        if tor.is_onion_url(url) or (use_tor and self.tor.proxy()):
            return self.tor.fetch(url)
        return default_fetch(url)

    # ----- sites (built in, supplied, and your own) -----
    def outlets(self):
        """Every site in the Tor tab: name, home, kind, onion address and where that address came from."""
        out = []
        mine = {o["name"]: o for o in self.settings["my_outlets"] if isinstance(o, dict) and o.get("name")}
        saved = self.settings["onion_addresses"]
        for name, home, kind in sources.ONION_OUTLETS:
            if name in saved:
                src, addr = "set by you", saved[name]
            elif name in sources.SUPPLIED_ONIONS:
                src = "supplied, reached when tested" if name in sources.REACHED_ONIONS else "supplied, did not answer when tested"
                addr = sources.SUPPLIED_ONIONS[name]
            else:
                src, addr = "none yet", ""
            out.append({"name": name, "home": home, "kind": kind, "onion": addr, "origin": src, "custom": False})
        for o in mine.values():
            addr = saved.get(o["name"]) or o.get("onion", "")
            out.append({"name": o["name"], "home": o.get("home", ""), "kind": o.get("kind", "news"), "onion": addr,
                        "origin": "yours" if addr else "none yet", "custom": True})
        return out

    def add_outlet(self, name, home="", onion=""):
        name = (name or "").strip()[:60]
        if not name:
            raise ValueError("Give the site a name.")
        if any(o["name"].lower() == name.lower() for o in self.outlets()):
            raise ValueError("A site with that name is already in the list.")
        home = (home or "").strip()
        if home:
            home = discover.normalize(home)
        onion = (onion or "").strip()
        if onion:
            if "://" not in onion:
                onion = "http://" + onion
            if not tor.is_onion_url(onion):
                raise ValueError("That is not a valid .onion address. A current one is 56 letters and numbers followed by .onion.")
            if not tor.onion_checksum_ok(urlparse(onion).hostname):
                raise ValueError("That onion address looks mistyped (its built-in check fails). Copy it again from the site itself.")
        if not home and not onion:
            raise ValueError("Give a website address, an onion address, or both.")
        if len(self.settings["my_outlets"]) >= 60:
            raise ValueError("That is the limit of 60 sites of your own.")
        self.settings["my_outlets"].append({"name": name, "home": home, "onion": onion, "kind": "news"})
        self.save_settings()

    def remove_outlet(self, name):
        self.settings["my_outlets"] = [o for o in self.settings["my_outlets"] if o.get("name") != name]
        self.settings["onion_addresses"].pop(name, None)
        self.save_settings()

    def set_onion_address(self, name, addr):
        """Saves an onion address typed or pasted by hand. Accepts it with or without http://."""
        addr = (addr or "").strip()
        if not addr:
            self.settings["onion_addresses"].pop(name, None)
            self.save_settings()
            return ""
        if "://" not in addr:
            addr = "http://" + addr
        if not tor.is_onion_url(addr):
            raise ValueError("That is not a valid .onion address. A current one is 56 letters and numbers followed by .onion.")
        if not tor.onion_checksum_ok(urlparse(addr).hostname):
            raise ValueError("That onion address looks mistyped (its built-in check fails). Copy it again from the site itself.")
        if not urlparse(addr).path:
            addr += "/"
        self.settings["onion_addresses"][name] = addr
        self.save_settings()
        return addr

    def find_feeds(self, address, say=None):
        return discover.find_feeds(self.fetch, address, say)

    # ----- settings -----
    def _load_settings(self):
        s = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_SETTINGS.items()}
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in s:
                    if k in data and type(data[k]) is type(s[k]):
                        s[k] = data[k]
        except (OSError, ValueError):
            pass
        s["home_states"] = [c for c in s["home_states"] if c in geo.STATES][:6]
        return s

    def save_settings(self):
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=1)
        os.replace(tmp, self.settings_path)

    def set_home_states(self, codes):
        codes = [c.strip().upper() for c in codes if c.strip()]
        bad = [c for c in codes if c not in geo.STATES]
        if bad:
            raise ValueError("Not a US state code: " + ", ".join(bad))
        self.settings["home_states"] = codes[:6]
        self.save_settings()

    def add_custom_feed(self, name, url, kind="news"):
        if not sources.valid_feed_url(url):
            raise ValueError("A feed address must start with https:// and use a website name (or be a .onion address).")
        if len(self.settings["custom_feeds"]) >= 30:
            raise ValueError("That is the limit of 30 custom feeds.")
        self.settings["custom_feeds"].append({"name": (name or "Custom feed").strip()[:60], "url": url.strip(),
                                              "kind": kind})
        self.save_settings()

    def remove_custom_feed(self, index):
        if 0 <= index < len(self.settings["custom_feeds"]):
            del self.settings["custom_feeds"][index]
            self.save_settings()

    # ----- cameras (set up in Settings > Watchtower; any number) -----
    def cameras(self):
        return list(self.settings["cameras"])

    def add_camera(self, name, brand_id, host, user="", password="", port=None, sub_host=""):
        cam = cameras.new_camera(name, brand_id, host, user, password, port, sub_host)
        self.settings["cameras"].append(cam)
        self.save_settings()
        return cam

    def watchtower(self):
        """How the Watchtower tab was left: mode (4, 6 or 1), the camera in each dock, and the single camera."""
        w = dict(self.settings.get("watchtower") or {})
        w["mode"] = w.get("mode") if w.get("mode") in (1, 4, 6) else 4
        w["slots"] = list(w.get("slots") or [])
        w.setdefault("one", "")
        w.setdefault("keep_days", 30)
        return w

    def set_watchtower(self, **kw):
        w = self.watchtower()
        w.update(kw)
        self.settings["watchtower"] = w
        self.save_settings()

    def link(self):
        """Phone link settings: whether it is on, the pairing token, and the relay port each camera keeps."""
        l = dict(self.settings.get("link") or {})
        l["enabled"] = bool(l.get("enabled", False))
        l.setdefault("token", "")
        l["ports"] = dict(l.get("ports") or {})
        return l

    def set_link_enabled(self, on):
        from . import link as _link
        l = self.link()
        l["enabled"] = bool(on)
        if on and not l["token"]:
            l["token"] = _link.new_token()
        self.settings["link"] = l
        self.save_settings()
        return l

    def new_link_code(self):
        """Makes a new token. Phones paired with the old one stop working."""
        from . import link as _link
        l = self.link()
        l["token"] = _link.new_token()
        self.settings["link"] = l
        self.save_settings()
        return l["token"]

    def link_port(self, cam_id):
        from . import link as _link
        l = self.link()
        before = dict(l["ports"])
        port = _link.assign_port(l["ports"], cam_id)
        if l["ports"] != before:
            self.settings["link"] = l
            self.save_settings()
        return port

    def remove_camera(self, cam_id):
        self.settings["cameras"] = [c for c in self.settings["cameras"] if c["id"] != cam_id]
        self.save_settings()

    def set_camera_enabled(self, cam_id, enabled):
        for c in self.settings["cameras"]:
            if c["id"] == cam_id:
                c["enabled"] = bool(enabled)
        self.save_settings()

    def set_source_enabled(self, source_id, enabled):
        dis = set(self.settings["disabled"])
        (dis.discard if enabled else dis.add)(source_id)
        self.settings["disabled"] = sorted(dis)
        self.save_settings()

    # ----- fetching -----
    def sources(self):
        return sources.all_sources(self.settings)

    def _pull(self, src):
        self._throttle(src["url"])
        status, text = self.fetch(src["url"])
        # GDELT allows one request every 5 seconds and blocks a connection for about 15 minutes after that. Asking again while
        # blocked only prolongs it, so a 429 is not retried: the source rests (see is_due) and other devices count too.
        if status == 429 and src["url"].startswith("https://api.gdeltproject.org"):
            raise feeds.FeedError("GDELT is limiting requests from your internet connection right now. Overwatch will try again in about 15 minutes.")
        if status != 200:
            raise feeds.FeedError("Could not reach it" + (f" (HTTP {status})" if status else (f": {text}" if text else "")))
        return feeds.PARSERS[src["parser"]](text, src, self.now())

    def refresh(self, progress=None, cancel=None, force=False):
        """Asks every source that is due. One broken source never stops the rest."""
        say = progress or (lambda m: None)
        now = self.now()
        health = self.store.health()
        def is_due(s):
            h = health.get(s["id"])
            if h is None:
                return True
            gap = now - (h["last_try"] or 0)
            # the refresh button never re-asks GDELT within 5 minutes of the last try: asking again is what makes it say 429
            # after GDELT refused us, leave it alone for 16 minutes: the block lasts about 15 and it only clears when not asked
            min_gap = (300 if h["ok"] else 960) if s["url"].startswith("https://api.gdeltproject.org") else 0
            return gap >= max(min_gap, 0 if force else s["every"] * 60)
        due = [s for s in self.sources() if is_due(s)]
        done, ok, failed, new = 0, 0, 0, 0
        results = []

        def work(src):
            if cancel is not None and cancel.is_set():
                return src, None, "Cancelled"
            try:
                return src, self._pull(src), ""
            except feeds.FeedError as e:
                return src, None, str(e)
            except Exception as e:      # a parser bug in one source must not take the scan down
                return src, None, f"Unexpected problem ({type(e).__name__})"

        # GDELT goes last: its spacing delays are long and must never hold the other sources back
        due.sort(key=lambda s: s["url"].startswith("https://api.gdeltproject.org"))
        with ThreadPoolExecutor(max_workers=6) as pool:
            for src, items, err in pool.map(work, due):
                done += 1
                say(f"Checked {done} of {len(due)} sources")
                if err == "Cancelled":
                    continue
                if items is None:
                    failed += 1
                    self.store.set_health(src["id"], False, 0, err, self.now())
                    continue
                ok += 1
                for it in items:
                    scoring.classify(it)
                results.extend(items)
                self.store.set_health(src["id"], True, len(items), "", self.now())
        new = self.store.upsert(results, self.now())
        self.store.prune(self.now() - KEEP_DAYS * 86400)
        self.store.set_meta("last_refresh", self.now())
        return {"asked": len(due), "ok": ok, "failed": failed, "new": new}

    # ----- what the screen shows -----
    def last_refresh(self):
        try:
            return float(self.store.get_meta("last_refresh", "0"))
        except ValueError:
            return 0.0

    def last_opened(self):
        try:
            return float(self.store.get_meta("last_opened", "0"))
        except ValueError:
            return 0.0

    def mark_opened(self):
        self.store.set_meta("prev_opened", self.last_opened())
        self.store.set_meta("last_opened", self.now())

    def since_last(self):
        """Number of items first seen since the user last looked, and when that was."""
        try:
            prev = float(self.store.get_meta("prev_opened", "0"))
        except ValueError:
            prev = 0.0
        return self.store.new_since(prev), prev

    def all_items(self, hours=72):
        return self.store.items(self.now() - hours * 3600)

    def top_warnings(self, n=10, region=None, min_severity=0):
        """The Top 10 for early warning, as (item, reasons), for the Intel dashboard. Filters apply before the ten are picked."""
        pool = [i for i in scoring.group(self.all_items(48)) if self.passes(i, region, min_severity)]
        return scoring.top_warnings(pool, self.settings["home_states"], self.now(), n=n)

    # ----- pins the owner places by hand -----
    def pin_item(self, uid, lat, lon, place="Pinned by you"):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("That is not a place on the map.")
        self.store.set_user_pin(uid, place or "Pinned by you", float(lat), float(lon), self.now())

    def pin_item_by_name(self, uid, text):
        """Pins a story at a place found in the built-in place list. Returns the place name, or '' if it is not known."""
        found = geo.find_place((text or "").strip())
        if not found:
            return ""
        self.pin_item(uid, found[1], found[2], found[0] + " (pinned by you)")
        return found[0]

    def unpin_item(self, uid):
        self.store.clear_user_pin(uid)

    def passes(self, it, region=None, min_severity=0):
        """The Intel filters. A region needs a pin, so a story that is not on the map is left out when one is chosen.
        'home' means within 1000 km of the home states."""
        if it.severity < min_severity:
            return False
        if not region:
            return True
        if not it.pinned:
            return False
        if region == "home":
            hp = geo.home_point(self.settings["home_states"])
            return hp is not None and geo.haversine_km(hp[0], hp[1], it.lat, it.lon) <= 1000
        return geo.region_of(it.lat, it.lon) == region

    def read_cached(self, url):
        return self.store.article(url)

    def cache_article(self, url, body):
        if body:
            self.store.save_article(url, body, self.now())

    def feed(self, kinds=None, home_only=False, text="", hours=72, limit=300, deploy_only=False, channel=None, region=None, min_severity=0):
        items = scoring.group(self.all_items(hours))
        hs = self.settings["home_states"]
        text = (text or "").strip().lower()
        out = []
        for it in items:
            if kinds and it.kind not in kinds:
                continue
            if home_only and not scoring.is_home(it, hs):
                continue
            if deploy_only and not scoring.is_deployment(it):
                continue
            if channel and sources.intel_channel(it) != channel:
                continue
            if not self.passes(it, region, min_severity):
                continue
            if text and text not in (it.title + " " + it.title_en + " " + it.summary + " " + it.source + " " + it.place).lower():
                continue
            out.append(it)
        return out[:limit]

    def indicators(self):
        return scoring.indicators(self.all_items(24 * 7), self.settings["home_states"], self.now())

    def source_status(self):
        health = self.store.health()
        rows = []
        for s in self.sources():
            h = health.get(s["id"])
            rows.append({**s, "health": h})
        return rows

    def healthy_counts(self):
        rows = self.source_status()
        return sum(1 for r in rows if r["health"] and r["health"]["ok"]), len(rows)

    def brief(self):
        now = self.now()
        lines = [f"Cindrix Overwatch brief, {time.strftime('%A %B %d, %Y %I:%M %p', time.localtime(now))}", ""]
        n, prev = self.since_last()
        lines.append(f"{n} new items since you last looked." if prev else "First time opening: everything is new.")
        lines += ["", "Status lights (based on how much is being reported, not on confirmed facts):"]
        for _, label, lvl, word, note in self.indicators():
            lines.append(f"  {label}: {word}. {note}")
        day = scoring.group(self.all_items(24))
        top = scoring.top_warnings(scoring.group(self.all_items(48)), self.settings["home_states"], now)
        lines += ["", "TOP 10 FOR EARLY WARNING (ranked by severity, force movements, home area, agreeing sources and freshness):"]
        from .model import TRUST_LABELS
        for k, (it, why) in enumerate(top, 1):
            tag = f"; {', '.join(why)}" if why else ""
            lines.append(f"  {k}. {it.shown} ({it.source}; {TRUST_LABELS[it.trust].lower()}{tag})")
        if not top:
            lines.append("  Nothing saved yet. Refresh while online.")
        home = [i for i in day if scoring.is_home(i, self.settings['home_states'])]
        lines += ["", f"Home ({', '.join(self.settings['home_states']) or 'not set'}): {len(home)} items."]
        for it in home[:8]:
            lines.append(f"  - {it.shown}")
        return "\n".join(lines)

    def export_sources(self, path=None):
        """Writes every source (built-in, yours, and the onion outlet list) to a CSV that opens in Excel."""
        import csv
        path = path or os.path.join(self.root, "overwatch-sources.csv")
        health = self.store.health()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Name", "Group", "Kind", "Trust", "Address", "Format", "Minutes between checks", "Status", "Notes"])
            for s in self.sources():
                h = health.get(s["id"])
                st = "not checked yet" if not h else ("working" if h["ok"] else "problem: " + (h["error"] or ""))
                w.writerow([s["name"], s["group"], s["kind"], s["trust"], s["url"], s["parser"], s["every"], st, ""])
            for o in self.outlets():
                w.writerow([o["name"], "Sites and onion addresses", o["kind"], "outlet", o["home"], "website", "",
                            "onion: " + o["origin"], o["onion"]])
        return path

    def clear_history(self):
        self.store.clear()

    def close(self):
        self.store.close()
        for closer in (self.tor.close, self.ai.stop):
            try:
                closer()
            except Exception:
                pass
