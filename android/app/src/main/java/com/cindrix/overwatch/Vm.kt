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
    var layers by mutableStateOf(setOf(Kind.MILITARY, Kind.CONFLICT, Kind.HAZARD, Kind.NEWS))
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
        val feedItems = engine.feed(limit = 400)
        val ind = engine.indicators()
        val src = engine.status()
        val n = engine.newSinceLast()
        val prev = engine.prevOpened()
        val last = engine.lastRefresh()
        val count = engine.store.count()
        val hs = engine.homeStates
        val hp = engine.geo.homePoint(hs)
        withContext(Dispatchers.Main) {
            items = feedItems; indicators = ind; sources = src; newCount = n; prevOpen = prev; lastRefresh = last
            storedCount = count; home = hs; homePoint = hp
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
