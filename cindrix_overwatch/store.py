"""Local history in one SQLite file. This is what keeps working when the internet does not."""

import os
import sqlite3
import threading

from .model import Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  uid TEXT PRIMARY KEY, source_id TEXT, source TEXT, kind TEXT, trust TEXT, title TEXT, url TEXT, summary TEXT,
  ts REAL, lat REAL, lon REAL, place TEXT, severity INTEGER, states TEXT, first_seen REAL, last_seen REAL);
CREATE INDEX IF NOT EXISTS items_ts ON items(ts);
CREATE TABLE IF NOT EXISTS health (
  source_id TEXT PRIMARY KEY, ok INTEGER, last_ok REAL, last_try REAL, count INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS translations (uid TEXT PRIMARY KEY, title_en TEXT, summary_en TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS ai_pins (uid TEXT PRIMARY KEY, place TEXT, lat REAL, lon REAL, ts REAL);
CREATE TABLE IF NOT EXISTS user_pins (uid TEXT PRIMARY KEY, place TEXT, lat REAL, lon REAL, ts REAL);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""
COLS = "uid,source_id,source,kind,trust,title,url,summary,ts,lat,lon,place,severity,states,first_seen,last_seen"


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()

    def upsert(self, items, now):
        """Adds items. An item seen before keeps its first_seen. Returns how many were new."""
        new = 0
        with self.lock:
            for it in items:
                row = self.db.execute("SELECT 1 FROM items WHERE uid=?", (it.uid,)).fetchone()
                vals = (it.source_id, it.source, it.kind, it.trust, it.title, it.url, it.summary, it.ts, it.lat,
                        it.lon, it.place, it.severity, ",".join(it.states), now)
                if row:
                    self.db.execute("UPDATE items SET source_id=?,source=?,kind=?,trust=?,title=?,url=?,summary=?,"
                                    "ts=?,lat=?,lon=?,place=?,severity=?,states=?,last_seen=? WHERE uid=?",
                                    vals + (it.uid,))
                else:
                    new += 1
                    self.db.execute(f"INSERT INTO items({COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (it.uid,) + vals[:-1] + (now, now))
            self.db.commit()
        return new

    @staticmethod
    def _item(r):
        it = Item(r[1], r[2], r[3], r[4], r[5], r[6] or "", r[7] or "", r[8] or 0.0, r[9], r[10], r[11] or "",
                  r[12] or 0, [s for s in (r[13] or "").split(",") if s], uid=r[0])
        it.first_seen = r[14] or 0.0
        return it

    def items(self, since_ts=0.0, limit=2000):
        with self.lock:
            rows = self.db.execute(f"SELECT {COLS} FROM items WHERE ts>=? ORDER BY ts DESC LIMIT ?",
                                   (since_ts, limit)).fetchall()
            tr = {r[0]: (r[1], r[2]) for r in self.db.execute("SELECT uid,title_en,summary_en FROM translations")}
            pins = {r[0]: (r[1], r[2], r[3]) for r in self.db.execute("SELECT uid,place,lat,lon FROM ai_pins WHERE lat IS NOT NULL")}
            mine = {r[0]: (r[1], r[2], r[3]) for r in self.db.execute("SELECT uid,place,lat,lon FROM user_pins")}
        out = [self._item(r) for r in rows]
        for it in out:
            if it.uid in mine:      # a pin the owner placed wins over everything else
                it.place, it.lat, it.lon, it.mine = mine[it.uid][0], mine[it.uid][1], mine[it.uid][2], True
        for it in out:
            # a place the model named for a story the built-in list could not place (never overrides a real pin)
            if it.lat is None and it.uid in pins and not it.mine:
                it.place, it.lat, it.lon = pins[it.uid][0] + " (placed by AI)", pins[it.uid][1], pins[it.uid][2]
        for it in out:
            if it.uid in tr:
                it.title_en, it.summary_en = tr[it.uid][0] or "", tr[it.uid][1] or ""
        return out

    # translations are kept in their own table so the original text is never touched
    def set_translation(self, uid, title_en, summary_en, now):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO translations VALUES (?,?,?,?)", (uid, title_en, summary_en, now))
            self.db.commit()

    # places named by the model; lat/lon come from the built-in place list, never from the model. A row with no
    # coordinates remembers "tried, no place" so the story is not asked about again.
    def set_ai_pin(self, uid, place, lat, lon, now):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO ai_pins VALUES (?,?,?,?,?)", (uid, place, lat, lon, now))
            self.db.commit()

    # pins the owner makes by hand; they survive refreshes and win over built-in and AI pins
    def set_user_pin(self, uid, place, lat, lon, now):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO user_pins VALUES (?,?,?,?,?)", (uid, place, lat, lon, now))
            self.db.commit()

    def clear_user_pin(self, uid):
        with self.lock:
            self.db.execute("DELETE FROM user_pins WHERE uid=?", (uid,))
            self.db.commit()

    def tried_ai_pin(self, uid):
        with self.lock:
            return self.db.execute("SELECT 1 FROM ai_pins WHERE uid=?", (uid,)).fetchone() is not None

    def tried_translation(self, uid):
        with self.lock:
            return self.db.execute("SELECT 1 FROM translations WHERE uid=?", (uid,)).fetchone() is not None

    def count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def new_since(self, ts):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM items WHERE first_seen>?", (ts,)).fetchone()[0]

    def prune(self, older_than_ts):
        with self.lock:
            self.db.execute("DELETE FROM items WHERE ts<? AND first_seen<?", (older_than_ts, older_than_ts))
            self.db.execute("DELETE FROM translations WHERE uid NOT IN (SELECT uid FROM items)")
            self.db.execute("DELETE FROM ai_pins WHERE uid NOT IN (SELECT uid FROM items)")
            self.db.execute("DELETE FROM user_pins WHERE uid NOT IN (SELECT uid FROM items)")
            self.db.commit()

    def clear(self):
        with self.lock:
            self.db.execute("DELETE FROM items")
            self.db.execute("DELETE FROM translations")
            self.db.execute("DELETE FROM ai_pins")
            self.db.execute("DELETE FROM user_pins")
            self.db.execute("DELETE FROM health")
            self.db.commit()

    # health of each source
    def set_health(self, source_id, ok, count, error, now):
        with self.lock:
            row = self.db.execute("SELECT last_ok FROM health WHERE source_id=?", (source_id,)).fetchone()
            last_ok = now if ok else (row[0] if row else None)
            self.db.execute("INSERT OR REPLACE INTO health VALUES (?,?,?,?,?,?)",
                            (source_id, 1 if ok else 0, last_ok, now, count, error or ""))
            self.db.commit()

    def health(self):
        with self.lock:
            rows = self.db.execute("SELECT source_id,ok,last_ok,last_try,count,error FROM health").fetchall()
        return {r[0]: {"ok": bool(r[1]), "last_ok": r[2], "last_try": r[3], "count": r[4], "error": r[5]} for r in rows}

    def get_meta(self, k, default=""):
        with self.lock:
            r = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def set_meta(self, k, v):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))
            self.db.commit()
