package com.cindrix.overwatch

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

private const val NOW = 1_800_000_000.0

private fun rfc(ts: Double): String =
    java.time.format.DateTimeFormatter.RFC_1123_DATE_TIME.format(java.time.Instant.ofEpochSecond(ts.toLong()).atOffset(java.time.ZoneOffset.UTC))

private fun rss(vararg items: Triple<String, String, Double>): String =
    "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>x</title>" +
        items.joinToString("") { "<item><title>${it.first}</title><link>${it.second}</link><description>d</description><pubDate>${rfc(it.third)}</pubDate></item>" } +
        "</channel></rss>"

class OverwatchTest {
    private val assets = File("src/main/assets")
    private val geo = Gazetteer(File(assets, "places.tsv").readText(), File(assets, "states.tsv").readText())
    private val feeds = Feeds(geo)
    private fun src(id: String, kind: Kind = Kind.NEWS, parser: String = "rss") = Src(id, id, "t", kind, Trust.WIRE, "https://example.org/x", parser)

    @Test fun gazetteerFindsPlacesAndStates() {
        assertEquals("Taiwan Strait", geo.findPlace("Warship near Taiwan Strait")?.name)
        assertEquals("West Virginia", geo.findPlace("West Virginia flood")?.name)
        assertEquals(listOf("TN", "WV"), geo.findStates("West Virginia and Tennessee"))
        assertEquals(listOf("WV"), geo.findStates("West Virginia"))
        assertNull(geo.findPlace("Local bakery wins award"))
        assertNull(geo.findPlace("Washington says US will respond"))
    }

    @Test fun rssPinsByHeadline() {
        val items = feeds.rss(src("a"), rss(
            Triple("Missile strike hits port city in Ukraine, dozens killed", "https://example.org/a1", NOW - 3600),
            Triple("Navy destroyer joins NATO exercise in the Baltic Sea", "https://example.org/a2", NOW - 7200),
            Triple("Local bakery wins award", "https://example.org/a3", NOW - 100)), NOW)
        assertEquals(3, items.size)
        assertEquals("Ukraine", items[0].place)
        assertEquals("Baltic Sea", items[1].place)
        assertFalse(items[2].pinned)
    }

    @Test fun atomWorks() {
        val x = "<?xml version=\"1.0\"?><feed xmlns=\"http://www.w3.org/2005/Atom\"><entry><title>Defence visit to fleet in Baltic Sea</title>" +
            "<link href=\"https://www.gov.uk/x\"/><updated>2027-01-15T07:00:00Z</updated><summary>s</summary></entry></feed>"
        val items = feeds.rss(src("m", Kind.MILITARY), x, NOW)
        assertEquals("https://www.gov.uk/x", items[0].url)
        assertEquals(1_800_000_000.0, items[0].ts, 86400.0)
    }

    @Test fun badFeedsAreRefused() {
        for (bad in listOf("<?xml version=\"1.0\"?><!DOCTYPE lolz [<!ENTITY a \"aaaa\">]><rss><channel><item><title>&a;</title></item></channel></rss>",
            "<html><body>blocked</body></html>", "not xml at all")) {
            try { feeds.rss(src("x"), bad, NOW); fail("should have been refused") } catch (e: FeedError) { /* expected */ }
        }
    }

    @Test fun linksMustBeHttp() {
        val items = feeds.rss(src("a"), rss(Triple("Some real title here", "javascript:alert(1)", NOW)), NOW)
        assertEquals("", items[0].url)
    }

    @Test fun usgsAndSwpcAndGdelt() {
        val usgs = """{"features":[{"id":"us1","properties":{"mag":6.2,"place":"30 km E of Somewhere, Japan","time":${((NOW - 600) * 1000).toLong()},"url":"https://e/u1"},"geometry":{"coordinates":[142.0,38.0,35.0]}},{"id":"bad","properties":{"mag":null},"geometry":{"coordinates":[0,0]}}]}"""
        val q = feeds.usgs(src("usgs", Kind.HAZARD, "usgs"), usgs)
        assertEquals(1, q.size)
        assertEquals(2, q[0].severity)
        assertEquals(38.0, q[0].lat!!, 0.001)
        val sw = feeds.swpc(src("swpc", Kind.SPACE, "swpc"), """{"0":{"G":{"Scale":"1","Text":"minor"},"S":{"Scale":"0"},"R":{"Scale":"0"}},"1":{"G":{"Scale":"2"},"S":{"Scale":"0"},"R":{"Scale":"1"}}}""", NOW)
        assertEquals(setOf("Geomagnetic storm", "Radio blackout"), sw.map { it.title.substringBefore(":") }.toSet())
        val gd = feeds.gdelt(src("gd", Kind.CONFLICT, "gdelt"), """{"articles":[{"url":"https://n.example.com/1","title":"Airstrike reported near Gaza border crossing","seendate":"20271231T120000Z","domain":"n.example.com"}]}""", NOW)
        assertEquals("Gaza", gd[0].place)
        try { feeds.gdelt(src("gd", Kind.CONFLICT, "gdelt"), "Your query was too short", NOW); fail() } catch (e: FeedError) { }
    }

    @Test fun nwsFallsBackToStateCentre() {
        val nws = """{"features":[{"id":"u1","properties":{"id":"u1","event":"Winter Weather Advisory","areaDesc":"Kanawha; Putnam","severity":"Minor","sent":"2027-01-15T07:00:00Z","headline":"h","geocode":{"UGC":["WVZ035"]},"@id":"https://api.weather.gov/alerts/1"},"geometry":null}]}"""
        val items = feeds.nws(src("nws-wv", Kind.WEATHER, "nws"), nws, NOW)
        assertEquals(listOf("WV"), items[0].states)
        assertTrue(items[0].pinned)
    }

    @Test fun classifyAndGroup() {
        val items = feeds.rss(src("a"), rss(
            Triple("Missile strike hits port city in Ukraine, dozens killed", "https://example.org/a1", NOW - 3600),
            Triple("Dozens killed after missile strike on Ukraine port city", "https://example.net/b1", NOW - 3000),
            Triple("Navy destroyer joins NATO exercise in the Baltic Sea", "https://example.org/a2", NOW - 7200)), NOW).map { classify(it) }
        assertEquals(listOf(Kind.CONFLICT, Kind.CONFLICT, Kind.MILITARY), items.map { it.kind })
        assertEquals(2, items[0].severity)
        val g = group(items)
        assertEquals(2, g.size)
        assertEquals(2, g.first { it.kind == Kind.CONFLICT }.count)
    }

    @Test fun indicatorsRespondToHomeWeather() {
        val nws = """{"features":[{"id":"u1","properties":{"id":"u1","event":"Winter Weather Advisory","areaDesc":"Kanawha","severity":"Minor","sent":"2027-01-15T07:00:00Z","geocode":{"UGC":["WVZ035"]}},"geometry":null}]}"""
        val items = feeds.nws(src("nws-wv", Kind.WEATHER, "nws"), nws, NOW)
        val ind = indicators(items, listOf("WV"), geo, NOW).associateBy { it.id }
        assertEquals("ADVISORY", ind["weather"]!!.word)
        assertEquals(8, ind.size)
        assertTrue(indicators(emptyList(), listOf("WV"), geo, NOW).all { it.level == 0 })
    }

    @Test fun customFeedUrlsMustBeHttpsWithName() {
        assertTrue(validFeedUrl("https://example.com/feed.xml"))
        assertFalse(validFeedUrl("http://example.com/feed.xml"))
        assertFalse(validFeedUrl("https://192.168.1.1/rss"))
        assertFalse(validFeedUrl("javascript:alert(1)"))
        assertTrue(BUILTIN_SOURCES.all { validFeedUrl(it.url) })
    }

    @Test fun sourceListCsvQuotesAndReportsStatus() {
        val a = Src("a", "Wire, \"One\"", "g", Kind.NEWS, Trust.WIRE, "https://example.org/a")
        val rows = listOf(
            SourceStatus(a, true, Health(true, NOW, NOW, 3, "")),
            SourceStatus(a, false, null),
            SourceStatus(a, true, Health(false, null, NOW, 0, "timeout")),
        )
        val lines = sourceListCsv(rows).trimEnd().split("\r\n")
        assertEquals(4, lines.size)
        assertTrue(lines[1].startsWith("\"Wire, \"\"One\"\"\","))
        assertTrue(lines[1].endsWith("\"working\""))
        assertTrue(lines[2].endsWith("\"turned off\""))
        assertTrue(lines[3].endsWith("\"problem: timeout\""))
    }

    @Test fun onionUrlAcceptsOnlyFullV3Addresses() {
        val host = "a".repeat(56) + ".onion"
        assertEquals("http://$host", onionUrl(host))
        assertEquals("http://$host/x", onionUrl(" HTTPS://$host/x "))
        assertNull(onionUrl("a".repeat(55) + ".onion"))
        assertNull(onionUrl("example.com"))
        assertNull(onionUrl(""))
        assertNull(onionUrl("1".repeat(56) + ".onion"))
    }
}
