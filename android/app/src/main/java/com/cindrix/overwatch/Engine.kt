package com.cindrix.overwatch

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.zip.GZIPInputStream

const val MAX_BYTES = 5_000_000
const val KEEP_DAYS = 30

data class CustomFeed(val name: String, val url: String, val kind: String)
data class SourceStatus(val src: Src, val enabled: Boolean, val health: Health?, val custom: Int = -1)
data class RefreshResult(val asked: Int, val ok: Int, val failed: Int, val added: Int)

fun nowSeconds(): Double = System.currentTimeMillis() / 1000.0

/** Real network access, https only. Returns (status, text). */
fun httpFetch(url: String): Pair<Int, String> {
    if (!url.lowercase().startsWith("https://")) return 0 to ""
    val host = URL(url).host
    val accept = if (host == "api.weather.gov") "application/geo+json"
    else "application/rss+xml, application/atom+xml, application/xml, application/json, text/xml, */*;q=0.8"
    var conn: HttpURLConnection? = null
    return try {
        conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15_000
            readTimeout = 25_000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", USER_AGENT)
            setRequestProperty("Accept", accept)
        }
        val code = conn.responseCode
        if (code != 200) return code to ""
        if (!conn.url.protocol.equals("https", true)) return 0 to ""
        var stream = conn.inputStream
        val buf = ByteArrayOutputStream()
        stream.use { s ->
            val tmp = ByteArray(16_384)
            while (buf.size() < MAX_BYTES) {
                val n = s.read(tmp)
                if (n < 0) break
                buf.write(tmp, 0, n)
            }
        }
        var bytes = buf.toByteArray()
        if (bytes.size > 2 && bytes[0] == 0x1f.toByte() && bytes[1] == 0x8b.toByte()) {
            bytes = GZIPInputStream(bytes.inputStream()).use { it.readBytes() }
        }
        200 to String(bytes, Charsets.UTF_8)
    } catch (e: Exception) {
        0 to (e.message ?: "").take(120)
    } finally {
        conn?.disconnect()
    }
}

class Engine(
    private val ctx: Context,
    private val fetch: (String) -> Pair<Int, String> = ::httpFetch,
    private val clock: () -> Double = ::nowSeconds,
) {
    val geo: Gazetteer = ctx.assets.let { a ->
        Gazetteer(a.open("places.tsv").bufferedReader().readText(), a.open("states.tsv").bufferedReader().readText())
    }
    val feeds = Feeds(geo)
    val store = Store(ctx)
    private val prefs = ctx.getSharedPreferences("overwatch", Context.MODE_PRIVATE)
    private val hostNext = HashMap<String, Long>()
    private val hostLock = Mutex()
    private val hostGaps = mapOf("api.gdeltproject.org" to 5500L)

    // ----- settings -----
    var homeStates: List<String>
        get() = (prefs.getString("home", "WV,TN") ?: "").split(",").map { it.trim().uppercase() }.filter { it in geo.states }
        set(v) { prefs.edit().putString("home", v.joinToString(",")).apply() }

    var disabled: Set<String>
        get() = prefs.getStringSet("disabled", emptySet()) ?: emptySet()
        set(v) { prefs.edit().putStringSet("disabled", v).apply() }

    var customFeeds: List<CustomFeed>
        get() = try {
            val arr = JSONArray(prefs.getString("custom", "[]"))
            (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                CustomFeed(o.getString("name"), o.getString("url"), o.optString("kind", "news"))
            }
        } catch (e: Exception) { emptyList() }
        set(v) {
            val arr = JSONArray()
            v.forEach { arr.put(JSONObject().put("name", it.name).put("url", it.url).put("kind", it.kind)) }
            prefs.edit().putString("custom", arr.toString()).apply()
        }

    fun setHome(text: String): String? {
        val codes = text.replace(";", ",").split(",").map { it.trim().uppercase() }.filter { it.isNotEmpty() }
        val bad = codes.filter { it !in geo.states }
        if (bad.isNotEmpty()) return "Not a US state code: " + bad.joinToString(", ")
        homeStates = codes.take(6)
        return null
    }

    fun addFeed(name: String, url: String, kind: String): String? {
        if (!validFeedUrl(url)) return "A feed address must start with https:// and use a website name."
        if (customFeeds.size >= 30) return "That is the limit of 30 custom feeds."
        customFeeds = customFeeds + CustomFeed(name.ifBlank { "Custom feed" }.take(60), url.trim(), kind)
        return null
    }

    fun removeFeed(index: Int) {
        val l = customFeeds.toMutableList()
        if (index in l.indices) { l.removeAt(index); customFeeds = l }
    }

    fun setEnabled(id: String, enabled: Boolean) { disabled = if (enabled) disabled - id else disabled + id }

    // ----- sources -----
    fun allSources(): List<Src> {
        val custom = customFeeds.mapIndexedNotNull { i, c ->
            if (!validFeedUrl(c.url)) null
            else Src("custom-$i", c.name, "Mine", Kind.of(c.kind), Trust.OUTLET, c.url)
        }
        return nwsSources(homeStates) + BUILTIN_SOURCES + custom
    }

    fun status(): List<SourceStatus> {
        val h = store.health()
        val off = disabled
        return allSources().map { SourceStatus(it, it.id !in off, h[it.id], if (it.id.startsWith("custom-")) it.id.removePrefix("custom-").toInt() else -1) }
    }

    private suspend fun throttle(url: String) {
        val host = URL(url).host
        val gap = hostGaps[host] ?: return
        val wait = hostLock.withLock {
            val t = System.currentTimeMillis()
            val start = maxOf(t, hostNext[host] ?: 0L)
            hostNext[host] = start + gap
            start - t
        }
        if (wait > 0) delay(wait)
    }

    private suspend fun pull(src: Src): List<Item> {
        throttle(src.url)
        var (code, text) = fetch(src.url)
        if (code == 429 && src.url.contains("gdeltproject.org")) {
            delay(6500)
            throttle(src.url)
            val r = fetch(src.url); code = r.first; text = r.second
        }
        if (code != 200) throw FeedError("Could not reach it" + if (code != 0) " (HTTP $code)" else if (text.isNotEmpty()) ": $text" else "")
        return feeds.parse(src, text, clock())
    }

    /** Asks every source that is due. One broken source never stops the rest. */
    suspend fun refresh(force: Boolean, progress: (String) -> Unit = {}): RefreshResult = withContext(Dispatchers.IO) {
        val now = clock()
        val health = store.health()
        val off = disabled
        val due = allSources().filter {
            it.id !in off && (force || health[it.id] == null || now - health[it.id]!!.lastTry >= it.everyMinutes * 60)
        }
        val gate = Semaphore(6)
        var done = 0
        val results = coroutineScope {
            due.map { src ->
                async {
                    gate.withPermit {
                        val r = try {
                            Triple(src, pull(src), "")
                        } catch (e: FeedError) {
                            Triple(src, null, e.message ?: "failed")
                        } catch (e: Exception) {
                            Triple(src, null, "Unexpected problem (${e.javaClass.simpleName})")
                        }
                        synchronized(this@Engine) { done++; progress("Checked $done of ${due.size} sources") }
                        r
                    }
                }
            }.awaitAll()
        }
        var ok = 0
        var failed = 0
        val all = mutableListOf<Item>()
        for ((src, items, err) in results) {
            if (items == null) {
                failed++
                store.setHealth(src.id, false, 0, err, clock())
            } else {
                ok++
                items.forEach { classify(it) }
                all += items
                store.setHealth(src.id, true, items.size, "", clock())
            }
        }
        val added = store.upsert(all, clock())
        store.prune(clock() - KEEP_DAYS * 86400)
        store.setMeta("last_refresh", clock().toString())
        RefreshResult(due.size, ok, failed, added)
    }

    // ----- what the screens show -----
    fun lastRefresh(): Double = store.meta("last_refresh", "0").toDoubleOrNull() ?: 0.0
    fun lastOpened(): Double = store.meta("last_opened", "0").toDoubleOrNull() ?: 0.0
    fun markOpened() {
        store.setMeta("prev_opened", lastOpened().toString())
        store.setMeta("last_opened", clock().toString())
    }
    fun prevOpened(): Double = store.meta("prev_opened", "0").toDoubleOrNull() ?: 0.0
    fun newSinceLast(): Int = store.newSince(prevOpened())

    fun allItems(hours: Int = 72): List<Item> = store.items(clock() - hours * 3600)

    fun feed(kinds: Set<Kind>? = null, homeOnly: Boolean = false, text: String = "", hours: Int = 72, limit: Int = 300): List<Item> {
        val home = homeStates
        val q = text.trim().lowercase()
        return group(allItems(hours)).filter {
            (kinds == null || it.kind in kinds) &&
                (!homeOnly || isHome(it, home)) &&
                (q.isEmpty() || (it.title + " " + it.summary + " " + it.source + " " + it.place).lowercase().contains(q))
        }.take(limit)
    }

    fun indicators(): List<Indicator> = indicators(allItems(24 * 7), homeStates, geo, clock())

    fun brief(): String {
        val sb = StringBuilder()
        val fmt = java.text.SimpleDateFormat("EEEE MMMM dd, yyyy h:mm a", java.util.Locale.US)
        sb.append("Cindrix Overwatch brief, ").append(fmt.format(java.util.Date((clock() * 1000).toLong()))).append("\n\n")
        val n = newSinceLast()
        sb.append(if (prevOpened() > 0) "$n new items since you last looked." else "First time opening: everything is new.")
        sb.append("\n\nStatus lights (based on how much is being reported, not on confirmed facts):\n")
        indicators().forEach { sb.append("  ${it.label}: ${it.word}. ${it.note}\n") }
        val day = group(allItems(24))
        val top = day.sortedWith(compareByDescending<Item> { it.severity }.thenByDescending { it.ts }).take(12)
        sb.append("\nMost serious in the last 24 hours:\n")
        if (top.isEmpty()) sb.append("  Nothing saved yet. Refresh while online.\n")
        top.forEach {
            val more = if (it.count > 1) ", ${it.count} sources" else ""
            sb.append("  - ${it.title} (${it.source}; ${it.trust.label.lowercase()}$more)\n")
        }
        val home = day.filter { isHome(it, homeStates) }
        sb.append("\nHome (${homeStates.joinToString(", ").ifEmpty { "not set" }}): ${home.size} items.\n")
        home.take(8).forEach { sb.append("  - ${it.title}\n") }
        return sb.toString()
    }

    fun clearHistory() = store.clear()
}
