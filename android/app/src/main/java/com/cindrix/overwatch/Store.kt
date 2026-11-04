package com.cindrix.overwatch

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

data class Health(val ok: Boolean, val lastOk: Double?, val lastTry: Double, val count: Int, val error: String)

/** Local history in one SQLite file. This is what keeps working when the internet does not. */
class Store(ctx: Context) : SQLiteOpenHelper(ctx, "overwatch.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE items (uid TEXT PRIMARY KEY, source_id TEXT, source TEXT, kind TEXT, trust TEXT, title TEXT, " +
            "url TEXT, summary TEXT, ts REAL, lat REAL, lon REAL, place TEXT, severity INTEGER, states TEXT, first_seen REAL, last_seen REAL)")
        db.execSQL("CREATE INDEX items_ts ON items(ts)")
        db.execSQL("CREATE TABLE health (source_id TEXT PRIMARY KEY, ok INTEGER, last_ok REAL, last_try REAL, count INTEGER, error TEXT)")
        db.execSQL("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {}

    /** Adds items; one seen before keeps its first_seen. Returns how many were new. */
    @Synchronized
    fun upsert(items: List<Item>, now: Double): Int {
        var added = 0
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (it in items) {
                val cv = ContentValues().apply {
                    put("source_id", it.sourceId); put("source", it.source); put("kind", it.kind.name); put("trust", it.trust.name)
                    put("title", it.title); put("url", it.url); put("summary", it.summary); put("ts", it.ts)
                    put("lat", it.lat); put("lon", it.lon); put("place", it.place); put("severity", it.severity)
                    put("states", it.states.joinToString(",")); put("last_seen", now)
                }
                val updated = db.update("items", cv, "uid=?", arrayOf(it.uid))
                if (updated == 0) {
                    cv.put("uid", it.uid); cv.put("first_seen", now)
                    db.insert("items", null, cv)
                    added++
                }
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
        return added
    }

    @Synchronized
    fun items(sinceTs: Double, limit: Int = 2000): List<Item> {
        val out = mutableListOf<Item>()
        readableDatabase.rawQuery(
            "SELECT uid,source_id,source,kind,trust,title,url,summary,ts,lat,lon,place,severity,states,first_seen FROM items " +
                "WHERE ts>=? ORDER BY ts DESC LIMIT ?", arrayOf(sinceTs.toString(), limit.toString())).use { c ->
            while (c.moveToNext()) {
                val it = Item(c.getString(1), c.getString(2), Kind.of(c.getString(3)), Trust.of(c.getString(4)), c.getString(5),
                    c.getString(6) ?: "", c.getString(7) ?: "", c.getDouble(8),
                    if (c.isNull(9)) null else c.getDouble(9), if (c.isNull(10)) null else c.getDouble(10),
                    c.getString(11) ?: "", c.getInt(12), (c.getString(13) ?: "").split(",").filter { s -> s.isNotEmpty() }, c.getString(0))
                it.firstSeen = c.getDouble(14)
                out += it
            }
        }
        return out
    }

    @Synchronized
    fun count(): Int = readableDatabase.rawQuery("SELECT COUNT(*) FROM items", null).use { it.moveToFirst(); it.getInt(0) }

    @Synchronized
    fun newSince(ts: Double): Int =
        readableDatabase.rawQuery("SELECT COUNT(*) FROM items WHERE first_seen>?", arrayOf(ts.toString())).use { it.moveToFirst(); it.getInt(0) }

    @Synchronized
    fun prune(olderThan: Double) {
        writableDatabase.delete("items", "ts<? AND first_seen<?", arrayOf(olderThan.toString(), olderThan.toString()))
    }

    @Synchronized
    fun clear() {
        writableDatabase.delete("items", null, null)
        writableDatabase.delete("health", null, null)
    }

    @Synchronized
    fun setHealth(id: String, ok: Boolean, count: Int, error: String, now: Double) {
        val prev = health()[id]
        val lastOk = if (ok) now else prev?.lastOk
        val cv = ContentValues().apply {
            put("source_id", id); put("ok", if (ok) 1 else 0); put("last_ok", lastOk); put("last_try", now)
            put("count", count); put("error", error)
        }
        writableDatabase.insertWithOnConflict("health", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    @Synchronized
    fun health(): Map<String, Health> {
        val out = HashMap<String, Health>()
        readableDatabase.rawQuery("SELECT source_id,ok,last_ok,last_try,count,error FROM health", null).use { c ->
            while (c.moveToNext()) {
                out[c.getString(0)] = Health(c.getInt(1) == 1, if (c.isNull(2)) null else c.getDouble(2), c.getDouble(3), c.getInt(4), c.getString(5) ?: "")
            }
        }
        return out
    }

    @Synchronized
    fun meta(k: String, default: String = ""): String =
        readableDatabase.rawQuery("SELECT v FROM meta WHERE k=?", arrayOf(k)).use { if (it.moveToFirst()) it.getString(0) else default }

    @Synchronized
    fun setMeta(k: String, v: String) {
        val cv = ContentValues().apply { put("k", k); put("v", v) }
        writableDatabase.insertWithOnConflict("meta", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }
}
