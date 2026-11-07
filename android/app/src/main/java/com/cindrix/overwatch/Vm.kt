package com.cindrix.overwatch

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class FeedFilter(val label: String) { ALL("All"), MILITARY("Military"), HAZARDS("Hazards"), NEWS("News"), HOME("Home only") }

private const val AUTO_MINUTES = 15

class OverwatchViewModel(app: Application) : AndroidViewModel(app) {
    val engine = Engine(app)

    var ready by mutableStateOf(false)
    var tab by mutableStateOf(0)
    var items by mutableStateOf<List<Item>>(emptyList())
    var indicators by mutableStateOf<List<Indicator>>(emptyList())
    var sources by mutableStateOf<List<SourceStatus>>(emptyList())
    var newCount by mutableStateOf(0)
    var prevOpen by mutableStateOf(0.0)
    var lastRefresh by mutableStateOf(0.0)
    var storedCount by mutableStateOf(0)
    var home by mutableStateOf<List<String>>(emptyList())
    var homePoint by mutableStateOf<Pair<Double, Double>?>(null)
    var refreshing by mutableStateOf(false)
    var progress by mutableStateOf("")
    var selected by mutableStateOf<Item?>(null)
    var centerOn by mutableStateOf<Item?>(null)
    var layers by mutableStateOf(setOf(Kind.MILITARY, Kind.CONFLICT, Kind.HAZARD, Kind.WEATHER, Kind.NEWS))
    var deployOn by mutableStateOf(true)
    var mineOn by mutableStateOf(true)
    var channel by mutableStateOf("military")
    var intelDash by mutableStateOf(true)
    var top by mutableStateOf<List<Pair<Item, List<String>>>>(emptyList())
    var troopsOnly by mutableStateOf(false)
    var intelSearch by mutableStateOf("")
    /** The story waiting for a tap on the map to be pinned. */
    var pinTarget by mutableStateOf<Item?>(null)
    var reader by mutableStateOf<Item?>(null)
    var readerText by mutableStateOf("")
    var readerNote by mutableStateOf("")
    var pinNote by mutableStateOf("")
    var filter by mutableStateOf(FeedFilter.ALL)
    var search by mutableStateOf("")
    var brief by mutableStateOf("")
    var message by mutableStateOf("")
    var aiUrl by mutableStateOf(engine.aiUrl)
    var aiNote by mutableStateOf("")
    var translateOn by mutableStateOf(engine.translateOn)
    var torNote by mutableStateOf("")

    init {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { engine.markOpened() }
            reload()
            ready = true
            refresh(false)
            while (true) {
                delay(60_000)
                if (nowSeconds() - engine.lastRefresh() > AUTO_MINUTES * 60) refresh(false)
            }
        }
    }

    suspend fun reload() = withContext(Dispatchers.IO) {
        val feedItems = engine.feed(limit = 700)
        val ind = engine.indicators()
        val src = engine.status()
        val n = engine.newSinceLast()
        val prev = engine.prevOpened()
        val last = engine.lastRefresh()
        val count = engine.store.count()
        val hs = engine.homeStates
        val hp = engine.geo.homePoint(hs)
        val tp = engine.topWarnings()
        withContext(Dispatchers.Main) {
            items = feedItems; indicators = ind; sources = src; newCount = n; prevOpen = prev; lastRefresh = last
            storedCount = count; home = hs; homePoint = hp; top = tp
        }
    }

    fun refresh(force: Boolean) {
        if (refreshing) return
        refreshing = true
        progress = "Refreshing..."
        viewModelScope.launch {
            try {
                engine.refresh(force) { p -> progress = p }
            } catch (e: Exception) {
                progress = "Refresh problem: ${e.javaClass.simpleName}"
            }
            reload()
            refreshing = false
            progress = ""
            runAiExtras()
        }
    }

    /** After a refresh: translate new foreign headlines and place unpinned stories, when an AI server is set. */
    private fun runAiExtras() {
        if (aiUrl.isEmpty() && !translateOn) return
        viewModelScope.launch {
            val changed = withContext(Dispatchers.IO) {
                var n = 0
                try { n += engine.autoTranslate() } catch (e: Exception) { }
                try { n += engine.autoPin() } catch (e: Exception) { }
                n
            }
            if (changed > 0) reload()
        }
    }

    fun toggleTranslate() {
        engine.translateOn = !engine.translateOn
        translateOn = engine.translateOn
        if (translateOn) runAiExtras()
    }

    fun saveAiUrl(text: String) {
        val err = engine.setAiUrl(text)
        aiNote = err ?: if (engine.aiUrl.isEmpty()) "AI is off." else "Saved. Unpinned stories will be placed on the map after the next refresh."
        if (err == null) { aiUrl = engine.aiUrl; if (aiUrl.isNotEmpty()) runAiExtras() }
    }

    fun checkTor() {
        torNote = "Checking..."
        viewModelScope.launch {
            val port = withContext(Dispatchers.IO) { Tor.proxyPort() }
            torNote = if (port != null) "Tor is running on this phone (port $port). Onion feeds will work."
            else "No Tor found. Install Orbot, open it and connect, then check again."
        }
    }

    fun select(item: Item?, centre: Boolean = false) {
        selected = item
        if (centre && item != null && item.pinned) {
            centerOn = item
            tab = 0
        }
    }

    /** Whether a pinned story is drawn on the map under the current buttons. */
    fun onMap(it: Item): Boolean =
        it.pinned && (layerOf(it.kind) in layers || (deployOn && isDeployment(it)) || (mineOn && it.mine))

    fun intelList(): List<Item> {
        val q = intelSearch.trim().lowercase()
        return items.filter {
            intelChannel(it) == channel && (!troopsOnly || isDeployment(it)) &&
                (q.isEmpty() || (it.title + " " + it.summary + " " + it.source + " " + it.place).lowercase().contains(q))
        }.take(200)
    }

    /** What a dashboard panel shows: the newest five, the home area first for alerts. */
    fun dashRows(id: String): List<Item> {
        val now = nowSeconds()
        val l = items.filter { intelChannel(it) == id && now - it.ts <= 48 * 3600 }
        return (if (id == "alerts") l.sortedWith(compareBy<Item>({ !isHome(it, home) }, { -it.severity }, { -it.ts })) else l).take(5)
    }

    fun troopRows(): List<Item> {
        val now = nowSeconds()
        return items.filter { isDeployment(it) && now - it.ts <= 24 * 3600 }.take(5)
    }

    fun seeAll(id: String, troops: Boolean = false) {
        channel = id; troopsOnly = troops; intelSearch = ""; intelDash = false
    }

    fun channelCount(id: String): Int = items.count { intelChannel(it) == id }

    fun openReader(item: Item) {
        reader = item; readerText = ""; readerNote = ""; pinNote = ""
        selected = item
        tab = 1
    }

    fun closeReader() { reader = null; readerText = ""; readerNote = ""; pinNote = "" }

    /** Fetches the article page and shows it as plain text. Only https pages; nothing is saved. */
    fun readArticle() {
        val item = reader ?: return
        readerNote = "Loading the article..."
        viewModelScope.launch {
            val (code, body) = withContext(Dispatchers.IO) { httpFetch(item.url) }
            if (reader?.uid != item.uid) return@launch
            if (code != 200) { readerNote = "Could not load the page here" + (if (code != 0) " (HTTP $code)" else "") + ". Use Open in browser instead."; return@launch }
            val text = htmlToText(body)
            if (text.isBlank()) readerNote = "This page has no text Overwatch can show (it may need a browser). Use Open in browser instead."
            else { readerText = text; readerNote = "" }
        }
    }

    /** Next tap on the map pins this story. */
    fun startPin(item: Item) {
        pinTarget = item; pinNote = ""; tab = 0
    }

    fun cancelPin() { pinTarget = null }

    fun placePin(lat: Double, lon: Double) {
        val item = pinTarget ?: return
        pinTarget = null
        viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) {
                try { engine.pinItem(item.uid, lat, lon, "Pinned by you (%.2f, %.2f)".format(lat, lon)); true } catch (e: IllegalArgumentException) { false }
            }
            pinNote = if (ok) "Pinned." else "That spot is off the map."
            reload()
            items.firstOrNull { it.uid == item.uid }?.let { selected = it; if (reader?.uid == it.uid) reader = it }
        }
    }

    fun pinByName(item: Item, text: String) {
        viewModelScope.launch {
            val place = withContext(Dispatchers.IO) { engine.pinItemByName(item.uid, text) }
            pinNote = if (place.isEmpty()) "Overwatch does not know that place. Try a city, country or sea name, or tap the map instead." else "Pinned to $place."
            reload()
            items.firstOrNull { it.uid == item.uid }?.let { selected = it; if (reader?.uid == it.uid) reader = it }
        }
    }

    fun removePin(item: Item) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { engine.unpinItem(item.uid) }
            pinNote = "Your pin was removed."
            reload()
            items.firstOrNull { it.uid == item.uid }?.let { selected = it; if (reader?.uid == it.uid) reader = it }
        }
    }

    fun toggleLayer(k: Kind) { layers = if (k in layers) layers - k else layers + k }

    fun visibleFeed(): List<Item> {
        val q = search.trim().lowercase()
        return items.filter {
            when (filter) {
                FeedFilter.ALL -> true
                FeedFilter.MILITARY -> it.kind == Kind.MILITARY
                FeedFilter.HAZARDS -> it.kind in setOf(Kind.HAZARD, Kind.WEATHER, Kind.SPACE, Kind.HEALTH)
                FeedFilter.NEWS -> it.kind == Kind.NEWS || it.kind == Kind.CONFLICT
                FeedFilter.HOME -> isHome(it, home)
            } && (q.isEmpty() || (it.title + " " + it.summary + " " + it.source + " " + it.place).lowercase().contains(q))
        }.take(150)
    }

    fun loadBrief() {
        viewModelScope.launch { brief = withContext(Dispatchers.IO) { engine.brief() } }
    }

    fun saveHome(text: String) {
        val err = engine.setHome(text)
        message = err ?: "Saved. Refreshing home weather."
        if (err == null) { viewModelScope.launch { reload(); refresh(true) } }
    }

    fun addFeed(name: String, url: String, kind: String): String? {
        val err = engine.addFeed(name, url, kind)
        if (err == null) { viewModelScope.launch { reload(); refresh(true) } }
        return err
    }

    fun removeFeed(index: Int) { engine.removeFeed(index); viewModelScope.launch { reload() } }

    fun setEnabled(id: String, on: Boolean) { engine.setEnabled(id, on); viewModelScope.launch { reload() } }

    fun clearHistory() { viewModelScope.launch { withContext(Dispatchers.IO) { engine.clearHistory() }; reload() } }
}
