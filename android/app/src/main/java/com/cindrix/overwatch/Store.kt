package com.cindrix.overwatch

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

data class Health(val ok: Boolean, val lastOk: Double?, val lastTry: Double, val count: Int, val error: String)

/** Local history in one SQLite file. This is what keeps working when the internet does not. */
class Store(ctx: Context) : SQLiteOpenHelper(ctx, "overwatch.db", null, 4) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE items (uid TEXT PRIMARY KEY, source_id TEXT, source TEXT, kind TEXT, trust TEXT, title TEXT, " +
            "url TEXT, summary TEXT, ts REAL, lat REAL, lon REAL, place TEXT, severity INTEGER, states TEXT, first_seen REAL, last_seen REAL)")
        db.execSQL("CREATE INDEX items_ts ON items(ts)")
        db.execSQL("CREATE TABLE health (source_id TEXT PRIMARY KEY, ok INTEGER, last_ok REAL, last_try REAL, count INTEGER, error TEXT)")
        db.execSQL("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
        addAiTables(db)
        addUserPinTable(db)
        addArticleTable(db)
    }

    private fun addArticleTable(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS articles (url TEXT PRIMARY KEY, body TEXT, ts REAL)")
    }

    private fun addUserPinTable(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS user_pins (uid TEXT PRIMARY KEY, place TEXT, lat REAL, lon REAL, ts REAL)")
    }

    private fun addAiTables(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS translations (uid TEXT PRIMARY KEY, title_en TEXT, summary_en TEXT, ts REAL)")
        db.execSQL("CREATE TABLE IF NOT EXISTS ai_pins (uid TEXT PRIMARY KEY, place TEXT, lat REAL, lon REAL, ts REAL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) addAiTables(db)
        if (oldVersion < 3) addUserPinTable(db)
        if (oldVersion < 4) addArticleTable(db)
    }

    // Translations and AI-named places live in their own tables so the original story is never touched.
    @Synchronized
    fun setTranslation(uid: String, titleEn: String, summaryEn: String, now: Double) {
        val cv = ContentValues().apply { put("uid", uid); put("title_en", titleEn); put("summary_en", summaryEn); put("ts", now) }
        writableDatabase.insertWithOnConflict("translations", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    @Synchronized
    fun triedTranslation(uid: String): Boolean =
        readableDatabase.rawQuery("SELECT 1 FROM translations WHERE uid=?", arrayOf(uid)).use { it.moveToFirst() }

    /** lat/lon come from the built-in place list, never from the model. A row with no coordinates means "tried, no place". */
    @Synchronized
    fun setAiPin(uid: String, place: String, lat: Double?, lon: Double?, now: Double) {
        val cv = ContentValues().apply { put("uid", uid); put("place", place); put("lat", lat); put("lon", lon); put("ts", now) }
        writableDatabase.insertWithOnConflict("ai_pins", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    @Synchronized
    fun triedAiPin(uid: String): Boolean =
        readableDatabase.rawQuery("SELECT 1 FROM ai_pins WHERE uid=?", arrayOf(uid)).use { it.moveToFirst() }

    /** A pin the person placed by hand. It is kept in its own table so the story is never touched, and it wins over every automatic pin. */
    @Synchronized
    fun setUserPin(uid: String, place: String, lat: Double, lon: Double, now: Double) {
        val cv = ContentValues().apply { put("uid", uid); put("place", place); put("lat", lat); put("lon", lon); put("ts", now) }
        writableDatabase.insertWithOnConflict("user_pins", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    /** Articles read in the reader are kept so they open again with no internet. */
    @Synchronized
    fun saveArticle(url: String, body: String, now: Double) {
        val cv = ContentValues().apply { put("url", url); put("body", body); put("ts", now) }
        writableDatabase.insertWithOnConflict("articles", null, cv, SQLiteDatabase.CONFLICT_REPLACE)
    }

    @Synchronized
    fun article(url: String): String? =
        readableDatabase.rawQuery("SELECT body FROM articles WHERE url=?", arrayOf(url)).use { if (it.moveToFirst()) it.getString(0) else null }

    @Synchronized
    fun clearUserPin(uid: String) { writableDatabase.delete("user_pins", "uid=?", arrayOf(uid)) }

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
        val tr = HashMap<String, Pair<String, String>>()
        readableDatabase.rawQuery("SELECT uid,title_en,summary_en FROM translations", null).use { c ->
            while (c.moveToNext()) tr[c.getString(0)] = (c.getString(1) ?: "") to (c.getString(2) ?: "")
        }
        val pins = HashMap<String, Triple<String, Double, Double>>()
        readableDatabase.rawQuery("SELECT uid,place,lat,lon FROM ai_pins WHERE lat IS NOT NULL", null).use { c ->
            while (c.moveToNext()) pins[c.getString(0)] = Triple(c.getString(1) ?: "", c.getDouble(2), c.getDouble(3))
        }
        val mine = HashMap<String, Triple<String, Double, Double>>()
        readableDatabase.rawQuery("SELECT uid,place,lat,lon FROM user_pins", null).use { c ->
            while (c.moveToNext()) mine[c.getString(0)] = Triple(c.getString(1) ?: "", c.getDouble(2), c.getDouble(3))
        }
        for (it in out) {
            val m = mine[it.uid]
            if (m != null) { it.place = m.first; it.lat = m.second; it.lon = m.third; it.mine = true }
            // a place the model named for a story the built-in list could not place (never overrides a real pin)
            val p = pins[it.uid]
            if (!it.mine && it.lat == null && p != null) { it.place = p.first + " (placed by AI)"; it.lat = p.second; it.lon = p.third }
            tr[it.uid]?.let { t -> it.titleEn = t.first; it.summaryEn = t.second }
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
        val db = writableDatabase
        db.delete("items", "ts<? AND first_seen<?", arrayOf(olderThan.toString(), olderThan.toString()))
        db.execSQL("DELETE FROM translations WHERE uid NOT IN (SELECT uid FROM items)")
        db.execSQL("DELETE FROM ai_pins WHERE uid NOT IN (SELECT uid FROM items)")
        db.execSQL("DELETE FROM user_pins WHERE uid NOT IN (SELECT uid FROM items)")
        db.delete("articles", "ts<?", arrayOf(olderThan.toString()))
    }

    @Synchronized
    fun clear() {
        writableDatabase.delete("items", null, null)
        writableDatabase.delete("translations", null, null)
        writableDatabase.delete("ai_pins", null, null)
        writableDatabase.delete("user_pins", null, null)
        writableDatabase.delete("articles", null, null)
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
