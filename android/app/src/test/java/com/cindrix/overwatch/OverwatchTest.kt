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
        assertEquals(9, ind.size)
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

    @Test fun aiAddressMustBeLocalOrHttps() {
        assertEquals("http://192.168.1.20:8080", validAiUrl("192.168.1.20:8080/"))
        assertEquals("http://localhost:8080", validAiUrl("http://localhost:8080"))
        assertEquals("https://ai.example.org", validAiUrl("https://ai.example.org"))
        assertNull(validAiUrl("http://example.org"))
        assertNull(validAiUrl("http://8.8.8.8:8080"))
        assertNull(validAiUrl("ftp://192.168.1.2"))
        assertNull(validAiUrl("http://192.168.1.2/path"))
        assertNull(validAiUrl(""))
    }

    @Test fun foreignHeadlinesAreSpottedAndEnglishIsLeftAlone() {
        assertTrue(looksForeign("Россия заявила о новых ударах по городам"))
        assertTrue(looksForeign("Le gouvernement a annoncé des mesures pour la sécurité des frontières"))
        assertFalse(looksForeign("Navy sends two destroyers to the Baltic Sea for an exercise"))
        assertEquals("", cleanTranslation("Sure, here is the translation", "Le gouvernement a annoncé"))
        assertEquals("The government announced measures", cleanTranslation("\"The government announced measures\"", "Le gouvernement a annoncé des mesures"))
    }

    @Test fun parsePlacesReadsNumberedLines() {
        val m = parsePlaces("1: Kyiv, Ukraine\n2: none\n3. **Gaza**\n9: Paris\nnoise", 3)
        assertEquals(setOf(1, 3), m.keys)
        assertEquals("Kyiv, Ukraine", m[1])
    }

    @Test fun onionAddressesAreFeedsReadThroughTor() {
        val host = "a".repeat(56) + ".onion"
        assertTrue(Tor.isOnionUrl("http://$host/feed.xml"))
        assertFalse(Tor.isOnionUrl("http://example.org/feed.xml"))
        assertTrue(validFeedUrl("http://$host/rss"))
        assertFalse(validFeedUrl("http://example.org/rss"))
    }

    @Test fun aiMayOnlyPickAPlaceTheHeadlineNames() {
        assertTrue(namesPlace("Fighting near Kherson, officials say", "Kherson, Ukraine"))
        assertTrue(namesPlace("Strike hits Ukraine power grid", "Kyiv, Ukraine"))
        assertFalse(namesPlace("Government says air defenses engaged overnight", "Kyiv, Ukraine"))
        assertFalse(namesPlace("Markets are calm today", "Paris"))
    }

    @Test fun citiesPinToTheCityNotTheCountry() {
        assertEquals(49.99, geo.findPlace("Kharkiv")!!.lat, 0.01)
        assertEquals(37.57, geo.findPlace("Seoul")!!.lat, 0.01)
        assertEquals("Gaza City", geo.findPlace("Strike in Gaza City overnight")!!.name)
        assertEquals("Washington DC", geo.findPlace("Washington DC")!!.name)
        assertEquals("Ukraine", geo.findPlace("Ukraine")!!.name)
    }

    private fun item(title: String, kind: Kind = Kind.NEWS, sev: Int = 0, src: String = "a", trust: Trust = Trust.WIRE, ts: Double = NOW - 3600, states: List<String> = emptyList()) =
        Item(src, src, kind, trust, title, "https://example.org/" + title.hashCode(), "", ts, severity = sev, states = states)

    @Test fun deploymentWordsAreSpotted() {
        assertTrue(isDeployment(item("US sends warships to the Red Sea", Kind.MILITARY)))
        assertTrue(isDeployment(item("Russia mobilises reservists near the border")))
        assertFalse(isDeployment(item("Navy band plays at ceremony", Kind.MILITARY)))
        assertFalse(isDeployment(item("New phishing kit sold online", Kind.CYBER)))
    }

    @Test fun intelChannelsCoverEveryKind() {
        for (k in Kind.entries) assertTrue(INTEL_CHANNELS.any { k in it.kinds })
        assertEquals("cyber", intelChannel(item("x", Kind.CYBER)))
        assertEquals("military", intelChannel(item("x", Kind.MILITARY)))
        assertEquals("world", intelChannel(item("x", Kind.CONFLICT)))
        assertEquals("alerts", intelChannel(item("x", Kind.SPACE)))
        assertEquals("alerts", intelChannel(item("Level 3: Reconsider travel", Kind.CONFLICT, src = "travel")))
    }

    @Test fun newFeedsAreInTheListAndGdeltIsHourly() {
        val ids = BUILTIN_SOURCES.map { it.id }.toSet()
        for (id in listOf("wotr", "taskpurpose", "airspace", "guardian", "travel", "cisa", "bleeping", "krebs", "thn")) assertTrue(id, id in ids)
        assertEquals(ids.size, BUILTIN_SOURCES.size)
        assertTrue(BUILTIN_SOURCES.filter { it.parser == "gdelt" }.all { it.everyMinutes == 60 })
        assertTrue(BUILTIN_SOURCES.filter { it.group == "Cyber" }.all { it.kind == Kind.CYBER })
    }

    @Test fun travelAdvisoryLevelSetsSeverity() {
        assertEquals(3, classify(item("Level 4: Do not travel to X", Kind.CONFLICT, src = "travel")).severity)
        assertEquals(1, classify(item("Level 2: Exercise increased caution in Y", Kind.CONFLICT, src = "travel")).severity)
    }

    @Test fun topTenRanksWarningsAndDropsNoise() {
        val items = listOf(
            item("Carrier strike group deployed near Taiwan Strait", Kind.MILITARY, 2, "dvids", Trust.OFFICIAL),
            item("Local team wins football final", Kind.NEWS, 0, "bbc"),
            item("Ransomware hits hospital chain", Kind.CYBER, 3, "cisa", Trust.OFFICIAL),
            item("Old story about troops", Kind.CONFLICT, 3, "un", ts = NOW - 5 * 86400),
            item("Flooding warning for county", Kind.WEATHER, 2, "nws-wv", Trust.OFFICIAL, states = listOf("WV")),
            item("Celebrity singer announces album", Kind.NEWS, 0, "npr"),
        )
        val top = topWarnings(items, listOf("WV"), NOW)
        val titles = top.map { it.first.title }
        assertFalse(titles.any { it.contains("football") || it.contains("Ransomware") || it.contains("Old story") || it.contains("singer") })
        assertEquals("Carrier strike group deployed near Taiwan Strait", titles.first())
        assertTrue(top.first().second.contains("force movement"))
        assertTrue(top.any { it.second.contains("home area") })
    }

    @Test fun oneSourceCannotFillTheTopTen() {
        val items = (1..8).map { item("Missile attack number $it on city $it", Kind.CONFLICT, 3, "same") }
        assertEquals(3, topWarnings(items, emptyList(), NOW).size)
        assertEquals(10, topWarnings((1..30).map { item("Attack on town $it killed people", Kind.CONFLICT, 2, "s${it % 12}") }, emptyList(), NOW).size)
    }

    @Test fun htmlBecomesReadableText() {
        val html = "<html><head><script>var x=1;</script><style>p{}</style></head><body><nav>Menu Home About</nav>" +
            "<p>The first paragraph of the story is long enough to keep, and it says &amp; things.</p>" +
            "<p>The second paragraph also has enough words to be kept as real article text here.</p>" +
            "<p>The third paragraph with a &quot;quote&quot; and more detail for readers to read.</p><footer>Copyright</footer></body></html>"
        val text = htmlToText(html)
        assertTrue(text.contains("says & things"))
        assertTrue(text.contains("\"quote\""))
        assertFalse(text.contains("var x"))
        assertFalse(text.contains("Menu Home"))
        assertFalse(text.contains("Copyright"))
        assertEquals(3, text.split("\n\n").size)
        assertTrue(htmlToText("<p>" + "word ".repeat(10000) + "</p>", 500).length <= 500)
    }
}
