package com.cindrix.overwatch

import java.net.URI

data class Src(
    val id: String, val name: String, val group: String, val kind: Kind, val trust: Trust,
    val url: String, val parser: String = "rss", val everyMinutes: Int = 30,
)

const val USER_AGENT = "CindrixOverwatch/0.1 (+https://github.com/Stormchyld2/Cindrix-Overwatch)"

private fun dod(site: Int) = "/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=$site&max=15"

private fun gdelt(q: String) =
    "https://api.gdeltproject.org/api/v2/doc/doc?query=$q%20sourcelang%3Aeng&mode=artlist&maxrecords=60&format=json&sort=datedesc&timespan=6h"

/** Same sources as the Windows app. Every one of these answered correctly from a real fetch (see tests/check_feeds.py). */
val BUILTIN_SOURCES = listOf(
    Src("usgs", "USGS earthquakes", "Hazards", Kind.HAZARD, Trust.OFFICIAL,
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson", "usgs", 15),
    Src("eonet", "NASA natural events", "Hazards", Kind.HAZARD, Trust.OFFICIAL,
        "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&days=7", "eonet", 60),
    Src("gdacs", "GDACS disaster alerts", "Hazards", Kind.HAZARD, Trust.OFFICIAL, "https://www.gdacs.org/xml/rss.xml", "gdacs", 30),
    Src("swpc", "NOAA space weather", "Hazards", Kind.SPACE, Trust.OFFICIAL,
        "https://services.swpc.noaa.gov/products/noaa-scales.json", "swpc", 30),
    Src("dvids", "DVIDS (all services)", "Military", Kind.MILITARY, Trust.OFFICIAL, "https://www.dvidshub.net/rss/news"),
    Src("defense", "Defense Department", "Military", Kind.MILITARY, Trust.OFFICIAL, "https://www.defense.gov" + dod(945)),
    Src("airforce", "US Air Force", "Military", Kind.MILITARY, Trust.OFFICIAL, "https://www.af.mil" + dod(1)),
    Src("centcom", "US Central Command", "Military", Kind.MILITARY, Trust.OFFICIAL, "https://www.centcom.mil" + dod(808)),
    Src("ukmod", "UK Ministry of Defence", "Military", Kind.MILITARY, Trust.OFFICIAL,
        "https://www.gov.uk/government/organisations/ministry-of-defence.atom"),
    Src("bbc", "BBC World", "News", Kind.NEWS, Trust.WIRE, "https://feeds.bbci.co.uk/news/world/rss.xml", everyMinutes = 20),
    Src("aljazeera", "Al Jazeera", "News", Kind.NEWS, Trust.WIRE, "https://www.aljazeera.com/xml/rss/all.xml", everyMinutes = 20),
    Src("dw", "Deutsche Welle", "News", Kind.NEWS, Trust.WIRE, "https://rss.dw.com/rdf/rss-en-world"),
    Src("npr", "NPR World", "News", Kind.NEWS, Trust.WIRE, "https://feeds.npr.org/1004/rss.xml"),
    Src("un", "UN News", "News", Kind.NEWS, Trust.OFFICIAL, "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
    Src("who", "WHO news", "Health", Kind.HEALTH, Trust.OFFICIAL, "https://www.who.int/rss-feeds/news-english.xml", everyMinutes = 120),
    Src("gdelt-conflict", "GDELT: conflict", "News", Kind.CONFLICT, Trust.OUTLET,
        gdelt("%28airstrike%20OR%20missile%20OR%20shelling%20OR%20offensive%29"), "gdelt", 60),
    Src("gdelt-military", "GDELT: military", "News", Kind.MILITARY, Trust.OUTLET,
        gdelt("%28navy%20OR%20warship%20OR%20%22air%20force%22%20OR%20troops%20OR%20nato%29"), "gdelt", 60),
    Src("wotr", "War on the Rocks", "Military", Kind.MILITARY, Trust.OUTLET, "https://warontherocks.com/feed/", everyMinutes = 60),
    Src("taskpurpose", "Task & Purpose", "Military", Kind.MILITARY, Trust.OUTLET, "https://taskandpurpose.com/feed/"),
    Src("airspace", "Air & Space Forces Magazine", "Military", Kind.MILITARY, Trust.OUTLET, "https://www.airandspaceforces.com/feed/"),
    Src("guardian", "The Guardian World", "News", Kind.NEWS, Trust.OUTLET, "https://www.theguardian.com/world/rss"),
    Src("travel", "State Dept travel advisories", "Conflict", Kind.CONFLICT, Trust.OFFICIAL, "https://travel.state.gov/_res/rss/TAsTWs.xml", everyMinutes = 120),
    Src("cisa", "CISA cyber advisories", "Cyber", Kind.CYBER, Trust.OFFICIAL, "https://www.cisa.gov/cybersecurity-advisories/all.xml", everyMinutes = 60),
    Src("bleeping", "BleepingComputer", "Cyber", Kind.CYBER, Trust.OUTLET, "https://www.bleepingcomputer.com/feed/"),
    Src("krebs", "Krebs on Security", "Cyber", Kind.CYBER, Trust.OUTLET, "https://krebsonsecurity.com/feed/", everyMinutes = 60),
    Src("thn", "The Hacker News", "Cyber", Kind.CYBER, Trust.OUTLET, "https://feeds.feedburner.com/TheHackersNews"),
)

/** The four reading channels of the Intel tab, the same as on the PC. */
data class Channel(val id: String, val label: String, val kinds: Set<Kind>)

val INTEL_CHANNELS = listOf(
    Channel("military", "Military", setOf(Kind.MILITARY)),
    Channel("world", "World news", setOf(Kind.NEWS, Kind.CONFLICT)),
    Channel("cyber", "Cyber", setOf(Kind.CYBER)),
    Channel("alerts", "Alerts and weather", setOf(Kind.HAZARD, Kind.WEATHER, Kind.SPACE, Kind.HEALTH)),
)

fun intelChannel(i: Item): String =
    if (i.sourceId == "travel") "alerts" else INTEL_CHANNELS.first { i.kind in it.kinds }.id

fun nwsSources(states: List<String>) = states.map {
    Src("nws-${it.lowercase()}", "Weather alerts: $it", "Home", Kind.WEATHER, Trust.OFFICIAL,
        "https://api.weather.gov/alerts/active?area=$it", "nws", 10)
}

/** Custom feeds must be https and use a real website name, not a bare IP address. A .onion address may use http (Tor encrypts it). */
fun validFeedUrl(url: String?): Boolean {
    val u = url?.trim().orEmpty()
    return try {
        val uri = URI(u)
        val host = uri.host ?: return false
        if (Tor.isOnionHost(host)) return uri.scheme == "http" || uri.scheme == "https"
        uri.scheme == "https" && host.contains(".") && !host.matches(Regex("[\\d.]+")) && !host.contains(":")
    } catch (e: Exception) {
        false
    }
}
