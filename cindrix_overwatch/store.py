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
        return [self._item(r) for r in rows]

    def count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def new_since(self, ts):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM items WHERE first_seen>?", (ts,)).fetchone()[0]

    def prune(self, older_than_ts):
        with self.lock:
            self.db.execute("DELETE FROM items WHERE ts<? AND first_seen<?", (older_than_ts, older_than_ts))
            self.db.commit()

    def clear(self):
        with self.lock:
            self.db.execute("DELETE FROM items")
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
