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

from . import ai, discover, feeds, geo, scoring, sources, tor
from .store import Store

MAX_BYTES = 5_000_000
KEEP_DAYS = 30
DEFAULT_SETTINGS = {"home_states": ["WV", "TN"], "custom_feeds": [], "disabled": [], "auto_minutes": 15,
                    "onion_addresses": {}, "my_outlets": [], "ai_root": "", "ai_enabled": False,
                    "auto_translate": True, "ai_focus": True, "ai_instructions": ""}


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
        self.host_gaps = {"api.gdeltproject.org": 5.5}
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
        if status == 429 and src["url"].startswith("https://api.gdeltproject.org"):
            time.sleep(self.host_gaps.get("api.gdeltproject.org", 0) + 1)      # rate limited: wait once and retry
            self._throttle(src["url"])
            status, text = self.fetch(src["url"])
        if status != 200:
            raise feeds.FeedError("Could not reach it" + (f" (HTTP {status})" if status else (f": {text}" if text else "")))
        return feeds.PARSERS[src["parser"]](text, src, self.now())

    def refresh(self, progress=None, cancel=None, force=False):
        """Asks every source that is due. One broken source never stops the rest."""
        say = progress or (lambda m: None)
        now = self.now()
        health = self.store.health()
        due = [s for s in self.sources()
               if force or s["id"] not in health or now - (health[s["id"]]["last_try"] or 0) >= s["every"] * 60]
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

    def feed(self, kinds=None, home_only=False, text="", hours=72, limit=300, deploy_only=False):
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
        top = sorted(day, key=lambda i: (-i.severity, -i.ts))[:12]
        lines += ["", "Most serious in the last 24 hours:"]
        from .model import TRUST_LABELS
        for it in top:
            more = f", {it.count} sources" if it.count > 1 else ""
            lines.append(f"  - {it.shown} ({it.source}; {TRUST_LABELS[it.trust].lower()}{more})")
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
