package com.cindrix.overwatch

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import org.xmlpull.v1.XmlPullParser
import org.xmlpull.v1.XmlPullParserException
import org.xmlpull.v1.XmlPullParserFactory
import java.io.StringReader
import java.net.URI
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/** Turns what each source sends into Items. Pure functions: text in, items out, no network. */
class Feeds(private val geo: Gazetteer) {

    fun parse(src: Src, text: String, now: Double): List<Item> = when (src.parser) {
        "rss" -> rss(src, text, now)
        "page" -> page(src, text, now)
        "auto" -> if (looksLikeHtml(text)) page(src, text, now) else rss(src, text, now)
        "usgs" -> usgs(src, text)
        "nws" -> nws(src, text, now)
        "eonet" -> eonet(src, text, now)
        "gdacs" -> gdacs(src, text, now)
        "swpc" -> swpc(src, text, now)
        "gdelt" -> gdelt(src, text, now)
        else -> throw FeedError("Unknown kind of source.")
    }

    // ----- helpers -----
    private fun num(v: Any?): Double? = when (v) {
        is Number -> v.toDouble()
        is String -> v.toDoubleOrNull()
        else -> null
    }

    fun parseTime(text: String?, default: Double): Double {
        val t = text?.trim().orEmpty()
        if (t.isEmpty()) return default
        runCatching { return Instant.from(DateTimeFormatter.RFC_1123_DATE_TIME.parse(t)).epochSecond.toDouble() }
        runCatching { return OffsetDateTime.parse(t).toEpochSecond().toDouble() }
        runCatching { return Instant.parse(t).epochSecond.toDouble() }
        runCatching {
            return LocalDateTime.parse(t, DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'")).toEpochSecond(ZoneOffset.UTC).toDouble()
        }
        runCatching { return LocalDateTime.parse(t).toEpochSecond(ZoneOffset.UTC).toDouble() }
        return default
    }

    private fun stripHtml(s: String?): String {
        if (s.isNullOrEmpty()) return ""
        var t = s.replace(Regex("<[^>]+>"), " ")
        t = t.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"")
            .replace("&#39;", "'").replace("&apos;", "'").replace("&amp;", "&")
        return t.trim().replace(Regex("\\s+"), " ")
    }

    private fun finish(item: Item): Item {
        if (!item.pinned) {
            val p = geo.findPlace(item.title) ?: geo.findPlace(item.summary)
            if (p != null) {
                item.place = p.name
                item.lat = p.lat
                item.lon = p.lon
            }
        }
        item.states = (item.states + geo.findStates(item.title + " " + item.summary)).distinct().sorted()
        return item
    }

    private fun rejectDtd(text: String) {
        if (text.take(4000).uppercase().contains("<!DOCTYPE") || text.take(20000).uppercase().contains("<!ENTITY")) {
            throw FeedError("The feed contained a DTD, which Overwatch refuses to read.")
        }
    }

    // ----- RSS, RDF and Atom -----
    fun rss(src: Src, text: String, now: Double): List<Item> {
        rejectDtd(text)
        val out = mutableListOf<Item>()
        var root: String? = null
        try {
            val p = XmlPullParserFactory.newInstance().newPullParser()
            p.setInput(StringReader(text.trimStart('﻿').trim()))
            var depth = 0
            var entryDepth = -1
            var cur: String? = null
            val fields = HashMap<String, StringBuilder>()
            var href = ""
            var lat: Double? = null
            var lon: Double? = null
            var ev = p.eventType
            while (ev != XmlPullParser.END_DOCUMENT && out.size < 60) {
                when (ev) {
                    XmlPullParser.START_TAG -> {
                        depth++
                        val name = p.name.substringAfter(':').lowercase()
                        if (root == null) root = name
                        if (entryDepth < 0 && (name == "item" || name == "entry")) {
                            entryDepth = depth
                            fields.clear()
                            href = ""
                            lat = null
                            lon = null
                        } else if (entryDepth > 0 && depth == entryDepth + 1) {
                            cur = name
                            if (name == "link") p.getAttributeValue(null, "href")?.let { if (href.isEmpty()) href = it }
                        }
                    }
                    XmlPullParser.TEXT, XmlPullParser.CDSECT -> {
                        if (entryDepth > 0 && depth == entryDepth + 1 && cur != null) {
                            fields.getOrPut(cur) { StringBuilder() }.append(p.text)
                        }
                    }
                    XmlPullParser.END_TAG -> {
                        if (entryDepth > 0 && depth == entryDepth) {
                            val title = stripHtml(fields["title"]?.toString())
                            if (title.isNotEmpty()) {
                                var link = fields["link"]?.toString()?.trim().orEmpty().ifEmpty { href }
                                if (!link.lowercase().startsWith("http://") && !link.lowercase().startsWith("https://")) link = ""
                                val summary = stripHtml(
                                    listOf("description", "summary", "content", "encoded").firstNotNullOfOrNull { fields[it]?.toString() })
                                val ts = parseTime(
                                    listOf("pubdate", "published", "updated", "date").firstNotNullOfOrNull { fields[it]?.toString() }, now)
                                val point = fields["point"]?.toString()?.trim()?.split(Regex("\\s+"))
                                if (point != null && point.size == 2) {
                                    lat = point[0].toDoubleOrNull()
                                    lon = point[1].toDoubleOrNull()
                                } else {
                                    lat = fields["lat"]?.toString()?.trim()?.toDoubleOrNull()
                                    lon = (fields["long"] ?: fields["lon"])?.toString()?.trim()?.toDoubleOrNull()
                                }
                                val ok = lat != null && lon != null && lat!! in -90.0..90.0 && lon!! in -180.0..180.0
                                out += finish(Item(src.id, src.name, src.kind, src.trust, title, link, summary, ts,
                                    if (ok) lat else null, if (ok) lon else null))
                            }
                            entryDepth = -1
                            cur = null
                        } else if (entryDepth > 0 && depth == entryDepth + 1) {
                            cur = null
                        }
                        depth--
                    }
                }
                ev = p.next()
            }
        } catch (e: XmlPullParserException) {
            throw FeedError("Not a readable feed.")
        }
        if (out.isEmpty() && root !in setOf("rss", "feed", "rdf")) throw FeedError("This is not an RSS or Atom feed.")
        return out
    }

    // ----- websites that publish no feed: the article links on the page are read as if they were one -----
    fun looksLikeHtml(text: String): Boolean {
        val head = text.take(3000).lowercase()
        return "<html" in head || "<!doctype html" in head || "<body" in head
    }

    private val skipBlocks = Regex("(?is)<(script|style|nav|header|footer|aside|form|noscript|svg|button)\\b.*?</\\1>")
    private val notArticle = Regex("/(tag|tags|category|categories|author|authors|page|search|login|signin|register|contact|about|privacy|terms|cart|account|" +
        "subscribe|shop|store|wp-admin|feed|rss|donate|cdn-cgi)(/|$)|\\.(jpg|jpeg|png|gif|webp|pdf|zip|mp3|mp4|css|js)$", RegexOption.IGNORE_CASE)
    private val generic = Regex("^(read more|learn more|continue reading|more|view all|see all|click here|share|comments?|reply|next|previous|older|newer|home|menu|skip to content)\\W*$",
        RegexOption.IGNORE_CASE)
    private val dateInPath = Regex("/(20\\d\\d)[/-](0?[1-9]|1[0-2])(?:[/-](0?[1-9]|[12]\\d|3[01]))?(?:/|-|$)")

    /** A web page with no feed: its headline links become items. Dated by the address when it has a date, else by the first sight. */
    fun page(src: Src, text: String, now: Double): List<Item> {
        val html = skipBlocks.replace(text.take(600_000), " ")
        val heads = Regex("(?is)<h[1-4]\\b.*?</h[1-4]>").findAll(html).map { it.range }.toList()
        val arts = Regex("(?is)<(article|main)\\b.*?</\\1>").findAll(html).map { it.range }.toList()
        val base = try { java.net.URI(src.url) } catch (e: Exception) { throw FeedError("That address could not be read.") }
        val host = (base.host ?: "").lowercase().removePrefix("www.")
        val root = base.path.orEmpty().trimEnd('/')
        val seen = HashSet<String>()
        val cands = ArrayList<Triple<String, String, Boolean>>()
        for (m in Regex("(?is)<a\\b([^>]*)>(.*?)</a>").findAll(html)) {
            val href = Regex("(?is)href\\s*=\\s*[\"']([^\"']+)[\"']").find(m.groupValues[1])?.groupValues?.get(1)?.trim() ?: continue
            if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:") || href.startsWith("javascript:")) continue
            val label = stripHtml(m.groupValues[2])
            if (label.isEmpty() || generic.matches(label)) continue
            val u = try { base.resolve(unescapeAmp(href)).let { java.net.URI(it.scheme, it.authority, it.path, it.query, null) } } catch (e: Exception) { continue }
            if (u.scheme != "http" && u.scheme != "https") continue
            val h = (u.host ?: "").lowercase().removePrefix("www.")
            if (!(h == host || h.endsWith(".$host"))) continue
            val path = u.path.orEmpty()
            val url = u.toString()
            if (notArticle.containsMatchIn(path) || path.trimEnd('/') == "" || path.trimEnd('/') == root || url in seen) continue
            val inHead = heads.any { m.range.first in it }
            val inArt = arts.any { m.range.first in it }
            if (!(inHead || label.split(" ").size >= 5) || label.length < 18 || label.length > 220) continue
            seen += url
            cands += Triple(url, label, inHead || inArt)
        }
        val strong = cands.filter { it.third }
        val pick = if (strong.size >= 4) strong else cands
        val out = pick.take(40).map { (url, label, _) ->
            val d = dateInPath.find(URI(url).path.orEmpty())
            val ts = if (d != null) runCatching {
                LocalDateTime.of(d.groupValues[1].toInt(), d.groupValues[2].toInt(), d.groupValues[3].ifEmpty { "1" }.toInt(), 12, 0)
                    .toEpochSecond(ZoneOffset.UTC).toDouble()
            }.getOrDefault(now) else now
            finish(Item(src.id, src.name, src.kind, src.trust, label, url, "", minOf(ts, now))).also { it.dated = d != null }
        }
        if (out.isEmpty()) throw FeedError("No article links were found on that page. It may need a browser to load, or it may block automated readers.")
        return out
    }

    private fun unescapeAmp(s: String) = s.replace("&amp;", "&")

    // ----- JSON sources -----
    private fun obj(text: String): JSONObject = try {
        JSONObject(text)
    } catch (e: JSONException) {
        throw FeedError("This source did not send what was expected.")
    }

    fun usgs(src: Src, text: String): List<Item> {
        val feats = obj(text).optJSONArray("features") ?: throw FeedError("Not a USGS earthquake feed.")
        val out = mutableListOf<Item>()
        for (i in 0 until minOf(feats.length(), 200)) {
            val f = feats.optJSONObject(i) ?: continue
            val p = f.optJSONObject("properties") ?: continue
            val c = f.optJSONObject("geometry")?.optJSONArray("coordinates") ?: continue
            val mag = num(p.opt("mag")) ?: continue
            if (c.length() < 2) continue
            val sev = if (mag >= 7) 3 else if (mag >= 6) 2 else if (mag >= 5) 1 else 0
            val place = p.optString("place", "")
            out += Item(src.id, src.name, Kind.HAZARD, Trust.OFFICIAL,
                "M%.1f earthquake, %s".format(java.util.Locale.US, mag, place.ifEmpty { "unknown place" }),
                p.optString("url", ""), if (c.length() > 2) "Depth %.0f km.".format(java.util.Locale.US, c.optDouble(2)) else "",
                p.optDouble("time", 0.0) / 1000.0, c.getDouble(1), c.getDouble(0), place, sev, uid = "usgs-" + f.optString("id"))
        }
        return out
    }

    private fun centroid(geom: JSONObject?): Pair<Double, Double>? {
        try {
            val type = geom?.optString("type") ?: return null
            val coords = geom.getJSONArray("coordinates")
            val ring = when (type) {
                "Polygon" -> coords.getJSONArray(0)
                "MultiPolygon" -> coords.getJSONArray(0).getJSONArray(0)
                else -> return null
            }
            var la = 0.0
            var lo = 0.0
            for (i in 0 until ring.length()) {
                lo += ring.getJSONArray(i).getDouble(0)
                la += ring.getJSONArray(i).getDouble(1)
            }
            return if (ring.length() == 0) null else la / ring.length() to lo / ring.length()
        } catch (e: JSONException) {
            return null
        }
    }

    fun nws(src: Src, text: String, now: Double): List<Item> {
        val feats = obj(text).optJSONArray("features") ?: throw FeedError("Not a National Weather Service alert feed.")
        val out = mutableListOf<Item>()
        for (i in 0 until minOf(feats.length(), 150)) {
            val f = feats.optJSONObject(i) ?: continue
            val p = f.optJSONObject("properties") ?: continue
            val event = p.optString("event", "Weather alert")
            val area = p.optString("areaDesc", "")
            var sev = when (p.optString("severity")) { "Minor", "Moderate" -> 1; "Severe" -> 2; "Extreme" -> 3; else -> 0 }
            if (event.contains("Warning")) sev = maxOf(sev, 2)
            val ugc = p.optJSONObject("geocode")?.optJSONArray("UGC")
            val states = mutableSetOf<String>()
            if (ugc != null) for (k in 0 until ugc.length()) {
                val code = ugc.optString(k).take(2)
                if (code in geo.states) states += code
            }
            val sorted = states.sorted()
            var pt = centroid(f.optJSONObject("geometry"))
            if (pt == null && sorted.isNotEmpty()) geo.states[sorted[0]]?.let { pt = it.lat to it.lon }
            val id = p.optString("@id", f.optString("id", ""))
            out += Item(src.id, src.name, Kind.WEATHER, Trust.OFFICIAL, "$event: ${area.take(120)}", id,
                p.optString("headline", ""), parseTime(p.optString("sent").ifEmpty { p.optString("effective") }, now),
                pt?.first, pt?.second, area.take(80), sev, sorted, uid = "nws-" + f.optString("id", p.optString("id")))
        }
        return out
    }

    fun eonet(src: Src, text: String, now: Double): List<Item> {
        val events = obj(text).optJSONArray("events") ?: throw FeedError("Not a NASA EONET feed.")
        val out = mutableListOf<Item>()
        for (i in 0 until minOf(events.length(), 100)) {
            val e = events.optJSONObject(i) ?: continue
            val geoms = e.optJSONArray("geometry") ?: continue
            if (geoms.length() == 0) continue
            val g = geoms.optJSONObject(geoms.length() - 1) ?: continue
            val c = g.optJSONArray("coordinates") ?: continue
            if (g.optString("type") != "Point" || c.length() < 2) continue
            val cat = e.optJSONArray("categories")?.optJSONObject(0)?.optString("title", "Event") ?: "Event"
            val sev = if (cat == "Volcanoes" || cat == "Severe Storms") 2 else 1
            val link = e.optJSONArray("sources")?.optJSONObject(0)?.optString("url").orEmpty().ifEmpty { e.optString("link", "") }
            out += Item(src.id, src.name, Kind.HAZARD, Trust.OFFICIAL, "$cat: ${e.optString("title")}", link, "",
                parseTime(g.optString("date"), now), c.getDouble(1), c.getDouble(0), "", sev, uid = "eonet-" + e.optString("id"))
        }
        return out
    }

    fun gdacs(src: Src, text: String, now: Double): List<Item> {
        // GDACS is RSS with extra tags; the generic reader pins by georss:point and we add the alert level.
        val base = rss(src, text, now)
        val levels = Regex("<gdacs:alertlevel>([^<]+)</gdacs:alertlevel>", RegexOption.IGNORE_CASE).findAll(text).map { it.groupValues[1].trim().lowercase() }.toList()
        base.forEachIndexed { i, item ->
            item.kind = Kind.HAZARD
            item.severity = when (levels.getOrNull(i)) { "red" -> 3; "orange" -> 2; "green" -> 0; else -> 1 }
        }
        return base
    }

    fun swpc(src: Src, text: String, now: Double): List<Item> {
        val data = obj(text)
        val cur = data.optJSONObject("0") ?: throw FeedError("Not a NOAA space-weather scales feed.")
        val fc = data.optJSONObject("1")
        val names = linkedMapOf("G" to "Geomagnetic storm", "S" to "Solar radiation storm", "R" to "Radio blackout")
        val out = mutableListOf<Item>()
        for ((key, label) in names) {
            for ((whenKey, block) in listOf("now" to cur, "forecast" to fc)) {
                val b = block?.optJSONObject(key) ?: continue
                val scale = b.optString("Scale").toIntOrNull() ?: continue
                if (scale >= 1) {
                    val sev = if (scale == 1) 1 else if (scale <= 3) 2 else 3
                    val title = "$label: $key$scale (${if (whenKey == "now") "in progress" else "forecast, next day"})"
                    out += Item(src.id, src.name, Kind.SPACE, Trust.OFFICIAL, title, "https://www.swpc.noaa.gov/",
                        b.optString("Text", ""), now, severity = sev, uid = "swpc-$key-$whenKey-$scale")
                }
            }
        }
        return out
    }

    fun gdelt(src: Src, text: String, now: Double): List<Item> {
        val arts: JSONArray = try {
            JSONObject(text).optJSONArray("articles") ?: JSONArray()
        } catch (e: JSONException) {
            throw FeedError("GDELT did not send a list of articles.")
        }
        val out = mutableListOf<Item>()
        for (i in 0 until minOf(arts.length(), 75)) {
            val a = arts.optJSONObject(i) ?: continue
            val title = a.optString("title")
            val url = a.optString("url")
            if (title.isEmpty() || url.isEmpty()) continue
            out += finish(Item(src.id, src.name, src.kind, Trust.OUTLET, title, url, a.optString("domain"),
                parseTime(a.optString("seendate"), now)))
        }
        return out
    }
}
