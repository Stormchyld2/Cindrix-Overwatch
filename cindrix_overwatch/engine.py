"""The Overwatch brain with no window code: fetches sources, keeps history, answers what the screen asks.

Network access goes through one injectable function, so tests run without the internet.
"""

import json
import os
import time
import urllib.error
import threading
import urllib.request
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

from . import feeds, geo, scoring, sources
from .store import Store

MAX_BYTES = 5_000_000
KEEP_DAYS = 30
DEFAULT_SETTINGS = {"home_states": ["WV", "TN"], "custom_feeds": [], "disabled": [], "auto_minutes": 15}


def default_fetch(url, timeout=25):
    """Returns (status, text). Only https is allowed, including after redirects."""
    if not url.lower().startswith("https://"):
        return 0, ""
    req = urllib.request.Request(url, headers={"User-Agent": sources.UA,
                                         "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, text/xml, */*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if not r.geturl().lower().startswith("https://"):
                return 0, ""
            return r.status, r.read(MAX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
        return 0, str(e)[:120]


class Controller:
    def __init__(self, root, fetch=default_fetch, now=time.time):
        os.makedirs(root, exist_ok=True)
        self.root, self.fetch, self.now = root, fetch, now
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

    # ----- settings -----
    def _load_settings(self):
        s = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_SETTINGS.items()}
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
            raise ValueError("A feed address must start with https:// and use a website name.")
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

    def feed(self, kinds=None, home_only=False, text="", hours=72, limit=300):
        items = scoring.group(self.all_items(hours))
        hs = self.settings["home_states"]
        text = (text or "").strip().lower()
        out = []
        for it in items:
            if kinds and it.kind not in kinds:
                continue
            if home_only and not scoring.is_home(it, hs):
                continue
            if text and text not in (it.title + " " + it.summary + " " + it.source + " " + it.place).lower():
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
            lines.append(f"  - {it.title} ({it.source}; {TRUST_LABELS[it.trust].lower()}{more})")
        if not top:
            lines.append("  Nothing saved yet. Refresh while online.")
        home = [i for i in day if scoring.is_home(i, self.settings['home_states'])]
        lines += ["", f"Home ({', '.join(self.settings['home_states']) or 'not set'}): {len(home)} items."]
        for it in home[:8]:
            lines.append(f"  - {it.title}")
        return "\n".join(lines)

    def clear_history(self):
        self.store.clear()

    def close(self):
        self.store.close()
