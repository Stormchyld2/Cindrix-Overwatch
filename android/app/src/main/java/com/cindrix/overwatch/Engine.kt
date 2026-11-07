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
    private val torFetch: (String) -> Pair<Int, String> = Tor::fetch,
) {
    val geo: Gazetteer = ctx.assets.let { a ->
        Gazetteer(a.open("places.tsv").bufferedReader().readText(), a.open("states.tsv").bufferedReader().readText())
    }
    val feeds = Feeds(geo)
    val store = Store(ctx)
    private val prefs = ctx.getSharedPreferences("overwatch", Context.MODE_PRIVATE)
    private val hostNext = HashMap<String, Long>()
    private val hostLock = Mutex()
    private val hostGaps = mapOf("api.gdeltproject.org" to 15_000L)

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
        if (!validFeedUrl(url)) return "A feed address must start with https:// and use a website name (or be a full .onion address)."
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
            else Src("custom-$i", c.name, if (Tor.isOnionUrl(c.url)) "Mine (Tor)" else "Mine", Kind.of(c.kind), Trust.OUTLET, c.url)
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
        val get = if (Tor.isOnionUrl(src.url)) torFetch else fetch
        var (code, text) = get(src.url)
        // GDELT allows one request every 5 seconds and blocks a connection for about 15 minutes after that. Asking again while
        // blocked only prolongs it, so a 429 is not retried: the source rests (see refresh) and the other devices count too.
        if (code == 429 && src.url.contains("gdeltproject.org")) {
            throw FeedError("GDELT is limiting requests from your internet connection right now. Overwatch will try again in about 15 minutes.")
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
            // the refresh button never re-asks GDELT within 5 minutes of the last try: asking again is what makes it say 429
            val lastTry = health[it.id]?.lastTry
            // after GDELT refused us, leave it alone for 16 minutes: the block lasts about 15 and it only clears when not asked
            val minGap = if (it.url.contains("gdeltproject.org")) (if (health[it.id]?.ok == false) 960 else 300) else 0
            it.id !in off && (lastTry == null || now - lastTry >= maxOf(minGap, if (force) 0 else it.everyMinutes * 60))
        }.sortedBy { it.url.contains("gdeltproject.org") } // GDELT goes last so the plain feeds never wait behind its spacing
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

    /** The Intel filters. A region needs a pin, so a story not on the map is left out when one is chosen. "home" means within 1000 km of home. */
    fun passes(it: Item, region: String?, minSeverity: Int): Boolean {
        if (it.severity < minSeverity) return false
        if (region == null) return true
        if (!it.pinned) return false
        if (region == "home") {
            val hp = geo.homePoint(homeStates) ?: return false
            return haversineKm(hp.first, hp.second, it.lat!!, it.lon!!) <= 1000
        }
        return regionOf(it.lat!!, it.lon!!) == region
    }

    fun readCached(url: String): String? = store.article(url)
    fun cacheArticle(url: String, body: String) { if (body.isNotBlank()) store.saveArticle(url, body, clock()) }

    fun feed(kinds: Set<Kind>? = null, homeOnly: Boolean = false, text: String = "", hours: Int = 72, limit: Int = 300): List<Item> {
        val home = homeStates
        val q = text.trim().lowercase()
        return group(allItems(hours)).filter {
            (kinds == null || it.kind in kinds) &&
                (!homeOnly || isHome(it, home)) &&
                (q.isEmpty() || (it.title + " " + it.summary + " " + it.source + " " + it.place).lowercase().contains(q))
        }.take(limit)
    }

    // ----- pins the person places by hand -----
    fun pinItem(uid: String, lat: Double, lon: Double, place: String = "Pinned by you") {
        if (lat !in -90.0..90.0 || lon !in -180.0..180.0) throw IllegalArgumentException("That place is off the map.")
        store.setUserPin(uid, place.ifBlank { "Pinned by you" }.take(80), lat, lon, clock())
    }

    /** Pins a story to a place typed in words, using the built-in place list. Returns the place found, or "" when none matched. */
    fun pinItemByName(uid: String, text: String): String {
        val found = geo.findPlace(text.trim()) ?: return ""
        store.setUserPin(uid, found.name, found.lat, found.lon, clock())
        return found.name
    }

    fun unpinItem(uid: String) = store.clearUserPin(uid)

    /** The Top 10 for early warning with the reasons each one is there, for the Intel dashboard. */
    fun topWarnings(n: Int = 10, region: String? = null, minSeverity: Int = 0): List<Pair<Item, List<String>>> =
        topWarnings(group(allItems(48)).filter { passes(it, region, minSeverity) }, homeStates, clock(), n)

    fun indicators(): List<Indicator> = indicators(allItems(24 * 7), homeStates, geo, clock())

    fun brief(): String {
        val sb = StringBuilder()
        val fmt = java.text.SimpleDateFormat("EEEE MMMM dd, yyyy h:mm a", java.util.Locale.US)
        sb.append("Cindrix Overwatch brief, ").append(fmt.format(java.util.Date((clock() * 1000).toLong()))).append("\n\n")
        val n = newSinceLast()
        sb.append(if (prevOpened() > 0) "$n new items since you last looked." else "First time opening: everything is new.")
        sb.append("\n\nStatus lights (based on how much is being reported, not on confirmed facts):\n")
        indicators().forEach { sb.append("  ${it.label}: ${it.word}. ${it.note}\n") }
        sb.append("\nTOP 10 FOR EARLY WARNING (ranked by severity, force movement, home area, agreeing sources, trust and freshness):\n")
        val tops = topWarnings(group(allItems(48)), homeStates, clock())
        if (tops.isEmpty()) sb.append("  Nothing saved yet. Refresh while online.\n")
        tops.forEachIndexed { k, (it, why) ->
            sb.append("  ${k + 1}. ${it.shown} (${it.source}; ${it.trust.label.lowercase()}${if (why.isNotEmpty()) "; " + why.joinToString(", ") else ""})\n")
        }
        val day = group(allItems(24)).filter { it.kind != Kind.CYBER }
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

    // ----- the optional AI (a model server you run; see Ai.kt) -----
    var aiUrl: String
        get() = prefs.getString("ai_url", "") ?: ""
        set(v) { prefs.edit().putString("ai_url", v).apply() }

    /** Saves the AI server address. An empty one switches the AI off. Returns a plain-words problem, or null. */
    fun setAiUrl(text: String): String? {
        if (text.isBlank()) { aiUrl = ""; return null }
        val clean = validAiUrl(text) ?: return "That address does not work. Use the address of a computer on your own network, like http://192.168.1.20:8080, or an https address."
        aiUrl = clean
        return null
    }

    private fun ai(): AiClient = AiClient(aiUrl.ifEmpty { throw AiError("Set the AI server address in Settings first.") })

    var translateOn: Boolean
        get() = prefs.getBoolean("translate", true)
        set(v) { prefs.edit().putBoolean("translate", v).apply() }

    /** Translates new non-English headlines into English with ML Kit. A headline that cannot be translated is remembered; one that could not be tried (offline) is not. */
    fun autoTranslate(limit: Int = 30, translate: (List<String>) -> List<String?> = MlTranslate::translate): Int {
        if (!translateOn) return 0
        val todo = allItems(72).filter { it.titleEn.isEmpty() && looksForeign(it.title) && !store.triedTranslation(it.uid) }.take(limit)
        if (todo.isEmpty()) return 0
        var done = 0
        todo.zip(translate(todo.map { it.title })).forEach { (it, r) ->
            if (r == null) return@forEach
            val t = cleanTranslation(r, it.title)
            store.setTranslation(it.uid, t, "", clock())
            if (t.isNotEmpty()) done++
        }
        return done
    }

    /** Asks the model WHICH PLACE each unpinned story is about, then finds it in the built-in list. The model never gives coordinates. */
    fun autoPin(limit: Int = 24): Int {
        if (aiUrl.isEmpty()) return 0
        val client = ai()
        val todo = allItems(72).filter { !it.pinned && it.kind != Kind.SPACE && it.kind != Kind.WEATHER && !store.triedAiPin(it.uid) }.take(limit)
        if (todo.isEmpty()) return 0
        val lines = todo.mapIndexed { i, it -> "${i + 1}. ${sanitizeHeadline(it.shown)}" }.joinToString("\n")
        val out = client.chat(PIN_SYSTEM, "For each numbered headline, write one line `N: Place, Country`, or `N: none`. No other text.\n\n$lines", 60 + 24 * todo.size, 0.0)
        val named = parsePlaces(out, todo.size)
        var done = 0
        for ((i, it) in todo.withIndex()) {
            val name = named[i + 1]
            // "City, Country": try the most specific part first, or the country would win by length
            val nm = name?.replace(Regex("Washington,? D\\.?C\\.?"), "Washington DC")
            val found = if (nm == null || !namesPlace(it.shown, name)) null else geo.findPlace(nm.substringBefore(",")) ?: geo.findPlace(nm)
            if (found != null) { store.setAiPin(it.uid, found.name, found.lat, found.lon, clock()); done++ }
            else store.setAiPin(it.uid, "", null, null, clock())
        }
        return done
    }
}
