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

/** What the Intel filters offer. "Near home" is within 1000 km of the home states; the world regions are rough boxes and need a map pin. */
val REGION_CHOICES = listOf("Everywhere" to null, "Near home (1000 km)" to "home", "Americas" to "Americas", "Europe" to "Europe",
    "Middle East" to "Middle East", "Africa" to "Africa", "Asia-Pacific" to "Asia-Pacific")
val SEVERITY_CHOICES = listOf("Any severity" to 0, "Notice and up" to 1, "Warning and up" to 2, "Severe only" to 3)

/** One camera in the viewer: typed in on this phone, or handed over by the home PC. */
class ViewCam(val id: String, val name: String, val local: Camera?, val linked: LinkedCamera?)

class OverwatchViewModel(app: Application) : AndroidViewModel(app) {
    val engine = Engine(app)

    var ready by mutableStateOf(false)
    var tab by mutableStateOf(0)
    var watchtowerOn by mutableStateOf(false)
    var items by mutableStateOf<List<Item>>(emptyList())
    var indicators by mutableStateOf<List<Indicator>>(emptyList())
    var defconEst by mutableStateOf<Defcon.Estimate?>(null)
    var defconPub by mutableStateOf<Defcon.Public?>(null)
    var showDefcon by mutableStateOf(false)
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
    var regionLabel by mutableStateOf("Everywhere")
    var minSev by mutableStateOf(0)
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
            watchtowerOn = withContext(Dispatchers.IO) { engine.watchtowerOn() }
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
        val tp = engine.topWarnings(10, regionCode(), minSev)
        withContext(Dispatchers.Main) {
            defconEst = Defcon.estimate(ind); defconPub = engine.defconPublic()
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

    fun regionCode(): String? = REGION_CHOICES.firstOrNull { it.first == regionLabel }?.second

    /** The where / how serious filters. A region needs a pin. */
    fun ok(it: Item): Boolean {
        if (it.severity < minSev) return false
        val r = regionCode() ?: return true
        if (!it.pinned) return false
        if (r == "home") return homePoint?.let { hp -> haversineKm(hp.first, hp.second, it.lat!!, it.lon!!) <= 1000 } ?: false
        return regionOf(it.lat!!, it.lon!!) == r
    }

    fun setRegion(label: String) { regionLabel = label; viewModelScope.launch { reload() } }
    fun setSeverity(n: Int) { minSev = n; viewModelScope.launch { reload() } }

    fun intelList(): List<Item> {
        val q = intelSearch.trim().lowercase()
        return items.filter {
            intelChannel(it) == channel && ok(it) && (!troopsOnly || isDeployment(it)) &&
                (q.isEmpty() || (it.title + " " + it.summary + " " + it.source + " " + it.place).lowercase().contains(q))
        }.take(200)
    }

    /** What a dashboard panel shows: the newest five, the home area first for alerts. */
    fun dashRows(id: String): List<Item> {
        val now = nowSeconds()
        val l = items.filter { intelChannel(it) == id && now - it.ts <= 48 * 3600 && ok(it) }
        return (if (id == "alerts") l.sortedWith(compareBy<Item>({ !isHome(it, home) }, { -it.severity }, { -it.ts })) else l).take(5)
    }

    fun troopRows(): List<Item> {
        val now = nowSeconds()
        return items.filter { isDeployment(it) && now - it.ts <= 24 * 3600 && ok(it) }.take(5)
    }

    fun seeAll(id: String, troops: Boolean = false) {
        channel = id; troopsOnly = troops; intelSearch = ""; intelDash = false
    }

    fun channelCount(id: String): Int = items.count { intelChannel(it) == id && ok(it) }

    fun openReader(item: Item) {
        reader = item; readerText = ""; readerNote = ""; pinNote = ""
        selected = item
        tab = 1
        // a copy saved the last time this was read opens with no internet
        viewModelScope.launch {
            val saved = withContext(Dispatchers.IO) { engine.readCached(item.url) }
            if (saved != null && reader?.uid == item.uid && readerText.isEmpty()) { readerText = saved; readerNote = "Saved copy, readable with no internet." }
        }
    }

    fun closeReader() { reader = null; readerText = ""; readerNote = ""; pinNote = "" }

    /** Fetches the article page and shows it as plain text. Only https pages; nothing is saved. */
    fun readArticle() {
        val item = reader ?: return
        readerNote = "Loading the article..."
        viewModelScope.launch {
            val (code, body) = withContext(Dispatchers.IO) { httpFetch(item.url) }
            if (reader?.uid != item.uid) return@launch
            val saved = withContext(Dispatchers.IO) { engine.readCached(item.url) }
            if (code != 200) {
                if (saved != null) { readerText = saved; readerNote = "Could not reach the site. Showing the saved copy." }
                else readerNote = "Could not load the page here" + (if (code != 0) " (HTTP $code)" else "") + ". Use Open in browser instead."
                return@launch
            }
            val text = htmlToText(body)
            if (text.isBlank()) readerNote = "This page has no text Overwatch can show (it may need a browser). Use Open in browser instead."
            else {
                readerText = text; readerNote = ""
                withContext(Dispatchers.IO) { engine.cacheArticle(item.url, text) }
            }
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

    fun setWatchtowerShown(on: Boolean) {
        watchtowerOn = on
        if (!on && tab == 4) tab = 5
        viewModelScope.launch(Dispatchers.IO) { engine.setWatchtowerOn(on) }
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

    var cameras by mutableStateOf(engine.cameras)

    // ----- Watchtower viewer -----
    var linkedCams by mutableStateOf(engine.linked)
    /** The address the home PC answered on (its Wi-Fi address at home, its VPN address away), or null when it cannot be reached. */
    var linkHost by mutableStateOf<String?>(null)
    var linkNote by mutableStateOf("")
    var linkBusy by mutableStateOf(false)
    var lockMode by mutableStateOf(engine.lockMode)
    var wtMode by mutableStateOf(engine.wtMode)
    var wtOne by mutableStateOf(engine.wtOne)
    var wtSlots by mutableStateOf(engine.wtSlots)
    var alerts by mutableStateOf<List<Pair<String, String>>>(emptyList())

    /** Every camera the viewer can show: the ones typed in here plus the ones the home PC handed over. */
    fun viewCams(): List<ViewCam> = cameras.filter { it.enabled }.map { ViewCam(it.id, it.name, it, null) } + linkedCams.map { ViewCam("L" + it.id, it.name, null, it) }

    fun address(vc: ViewCam, sub: Boolean): String? = vc.local?.let { Cameras.streamAddress(it, sub) } ?: vc.linked?.let { l -> linkHost?.let { l.address(it, sub) } }

    fun chooseMode(m: Int) { wtMode = m; engine.wtMode = m }
    fun chooseOne(id: String) { wtOne = id; engine.wtOne = id }

    /** Fills the four docks with valid cameras (the saved ones first), so the 4-camera view is never empty while cameras exist. */
    fun fixedSlots(): List<String> {
        val ids = viewCams().map { it.id }
        val slots = (wtSlots + listOf("", "", "", "")).take(4).map { if (it in ids) it else "" }
        val spare = ids.filter { it !in slots }.toMutableList()
        return slots.map { it.ifEmpty { if (spare.isNotEmpty()) spare.removeAt(0) else "" } }
    }

    /** Puts a camera in a dock. If it was already in another dock the two swap. */
    fun placeInDock(id: String, dock: Int) {
        val s = fixedSlots().toMutableList()
        val at = s.indexOf(id)
        if (at >= 0 && at != dock) s[at] = s[dock]
        s[dock] = id
        wtSlots = s
        engine.wtSlots = s
    }

    fun chooseLock(m: LockMode) { lockMode = m; engine.lockMode = m }

    /** Finds the home PC (over Wi-Fi if at home, through the VPN if away) and fetches its camera list. */
    fun connectHome(ctx: android.content.Context) {
        val code = Link.parseCode(engine.linkCode) ?: run { linkNote = "No pairing code yet. Paste the one from your PC."; return }
        if (linkBusy) return
        linkBusy = true
        linkNote = "Looking for your home PC..."
        viewModelScope.launch {
            val note = withContext(Dispatchers.IO) {
                val conf = engine.wgConf.ifEmpty { null }
                if (conf != null && HomeLink.consentIntent(ctx) != null) {
                    linkHost = null
                    return@withContext "Allow the VPN first (Settings > Watchtower > Allow the VPN)."
                }
                val host = HomeLink.reachPc(ctx, code, conf)
                linkHost = host
                if (host == null) return@withContext "Could not reach your home PC. Check that Overwatch is running on it with the phone link on" +
                    (if (conf == null) ", and paste your VPN config to connect from away." else ", and that CindrixVPN is connected there.")
                val cams = HomeLink.fetchCameras(host, code.port, code.token)
                    ?: return@withContext "The PC answered but did not accept the code. Make sure the code is the newest one."
                engine.linked = cams
                linkedCams = cams
                "Connected" + (if (host == code.lan) " over your home Wi-Fi" else " through the VPN") + ". Got ${cams.size} camera" + (if (cams.size == 1) "" else "s") + "."
            }
            linkNote = note
            linkBusy = false
        }
    }

    fun saveLinkCode(text: String): String? = engine.saveLinkCode(text)

    fun saveWgConf(text: String): String? = engine.saveWgConf(text)

    fun hasWg(): Boolean = engine.wgConf.isNotEmpty()

    fun linkCodeText(): String = engine.linkCode

    fun addCamera(name: String, brandId: String, host: String, user: String, password: String, port: String): String? {
        val err = engine.addCamera(name, brandId, host, user, password, port.ifBlank { null })
        cameras = engine.cameras
        return err
    }

    fun removeCamera(id: String) { engine.removeCamera(id); cameras = engine.cameras }

    fun setCameraEnabled(id: String, on: Boolean) { engine.setCameraEnabled(id, on); cameras = engine.cameras }

    fun removeFeed(index: Int) { engine.removeFeed(index); viewModelScope.launch { reload() } }

    fun setEnabled(id: String, on: Boolean) { engine.setEnabled(id, on); viewModelScope.launch { reload() } }

    fun clearHistory() { viewModelScope.launch { withContext(Dispatchers.IO) { engine.clearHistory() }; reload() } }
}
