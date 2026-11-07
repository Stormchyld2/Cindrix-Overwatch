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

    @Test fun worldRegionsFromCoordinates() {
        assertEquals("Europe", regionOf(50.45, 30.52))
        assertEquals("Middle East", regionOf(31.77, 35.21))
        assertEquals("Americas", regionOf(38.9, -77.0))
        assertEquals("Africa", regionOf(-1.3, 36.8))
        assertEquals("Asia-Pacific", regionOf(25.0, 121.5))
        assertTrue(REGION_CHOICES.mapNotNull { it.second }.filter { it != "home" }.all { it in REGIONS })
    }

    // ----- cameras -----
    private val camCat get() = Cameras.parseCatalog(File(assets, "camera_catalog.json").readText())

    @Test fun cameraCatalogMatchesPcCopyAndIsWellFormed() {
        assertEquals(File("../../cindrix_overwatch/data/camera_catalog.json").readText(), File(assets, "camera_catalog.json").readText())
        val c = camCat
        assertTrue(c.brands.size >= 20)
        assertEquals(c.brands.size, c.brands.map { it.id }.toSet().size)
        c.brands.forEach { assertTrue(it.id, it.tier in c.tiers); if (it.tier == "no") assertEquals("", it.main) }
    }

    @Test fun cameraAddressesAndLogins() {
        val c = camCat
        assertEquals("rtsp://192.168.1.20:554/Preview_01_main", Cameras.buildAddress(c, "reolink", "192.168.1.20"))
        val cam = Cameras.newCamera(c, "Front", "other", "rtsp://admin:p%40ss@10.0.0.5:554/stream1")
        assertEquals("admin", cam.user)
        assertEquals("p@ss", cam.password)
        assertFalse(Cameras.shownAddress(cam).contains("p%40ss"))
        assertEquals("rtsp://admin:p%40ss@10.0.0.5:554/stream1", Cameras.streamAddress(cam))
    }

    @Test fun badCameraInputGivesPlainWords() {
        val c = camCat
        for (args in listOf(listOf("Door", "reolink", ""), listOf("Cloud", "ring", "10.0.0.2"), listOf("X", "reolink", "10.0.0.2", "", "", "99999"))) {
            try {
                Cameras.newCamera(c, args[0], args[1], args[2], port = args.getOrNull(5))
                fail("expected an error for $args")
            } catch (e: CameraError) { assertTrue(e.message!!.isNotEmpty()) }
        }
    }

    // ----- phone link -----
    @Test fun linkCodeMatchesThePcFormat() {
        val c = Link.parseCode("OW1/192.168.1.50/10.66.66.2/8099/K7Q2M9XD4PRTAB3C")!!
        assertEquals(LinkCode("192.168.1.50", "10.66.66.2", 8099, "K7Q2M9XD4PRTAB3C"), c)
        assertEquals(LinkCode(null, "10.66.66.2", 8099, "ABC"), Link.parseCode("OW1/-/10.66.66.2/8099/ABC"))
        for (bad in listOf("", "nonsense", "OW2/a/b/1/T", "OW1/a/b/x/T", "OW1/a/b/8099/T-T", "OW1/a/b/0/T")) assertNull(bad, Link.parseCode(bad))
    }

    @Test fun linkedCameraAddressUsesTheHostItWasReachedOn() {
        val json = """{"v":1,"cameras":[{"id":"a1","name":"Front","brand":"reolink","port":8601,"user":"admin","password":"p@ss",
            "main":{"scheme":"rtsp","path":"/Preview_01_main"},"sub":{"scheme":"rtsp","path":"/Preview_01_sub"}}]}"""
        val cam = Link.parseCameras(json).single()
        assertEquals("rtsp://admin:p%40ss@10.66.66.2:8601/Preview_01_main", cam.address("10.66.66.2"))
        assertEquals("rtsp://admin:p%40ss@192.168.1.50:8601/Preview_01_sub", cam.address("192.168.1.50", sub = true))
    }

    @Test fun vpnConfigIsRewrittenToOnlyCarryHomeTrafficForOverwatch() {
        val conf = """
            [Interface]
            PrivateKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
            Address = 10.66.66.3/32
            DNS = 1.1.1.1

            [Peer]
            PublicKey = BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=
            Endpoint = 203.0.113.9:51820
            AllowedIPs = 0.0.0.0/0, ::/0
            PersistentKeepalive = 25
        """.trimIndent()
        assertEquals(Link.WgInfo("10.66.66.3/32", "203.0.113.9:51820"), Link.wgInfo(conf))
        val out = Link.rewriteWg(conf, "com.cindrix.overwatch")!!
        assertTrue(out.contains("AllowedIPs = 10.66.66.0/24"))
        assertFalse(out.contains("0.0.0.0/0"))
        assertFalse(out.contains("DNS"))
        assertTrue(out.contains("IncludedApplications = com.cindrix.overwatch"))
        assertNull(Link.rewriteWg("[Interface]\nAddress = nonsense", "x"))
        assertNull(Link.wgInfo("hello"))
    }

    @Test fun aWebsiteWithNoFeedIsReadAsOne() {
        val html = """<html><head><title>County</title></head><body>
            <nav><a href="/news/menu-item-one-two-three-four">Menu item that should never be an article</a></nav>
            <main>
            <h2><a href="/news/2026/11/05/evacuation-order-for-river-road-residents">Evacuation order for River Road residents</a></h2>
            <h2><a href="/news/2026/11/04/boil-water-notice-lifted-in-north-district">Boil water notice lifted in North District</a></h2>
            <h2><a href="/news/storm-shelters-open-at-three-schools-tonight">Storm shelters open at three schools tonight</a></h2>
            <h2><a href="https://other.example.org/elsewhere-story-about-something-else">Elsewhere story about something else</a></h2>
            <h2><a href="/news/">Read more</a></h2>
            </main><footer><a href="/privacy-policy-and-terms-of-use-here">Privacy policy and terms of use here</a></footer></body></html>"""
        val src = Src("custom-0", "County", "Mine", Kind.NEWS, Trust.OUTLET, "https://county.example.gov/news/", "auto")
        val now = 1_800_000_000.0
        val items = feeds.parse(src, html, now)
        assertEquals(listOf("Evacuation order for River Road residents", "Boil water notice lifted in North District",
            "Storm shelters open at three schools tonight"), items.map { it.title })
        assertTrue(items[0].ts < now && items[0].dated)
        assertTrue(!items[2].dated)
        assertTrue(feeds.looksLikeHtml(html))
        assertTrue(runCatching { feeds.parse(src, "<html><body><p>Nothing here.</p></body></html>", now) }.isFailure)
    }

    @Test fun defconReadingEstimateAndPublicTracker() {
        val page = "<h1>DEFCON Level Threat Monitor</h1><p>LIVE &middot; <b>OSINT Estimate: DEFCON 3</b> &middot; Updated Nov 6, 2026 (UTC)</p>"
        assertEquals(3 to "Nov 6, 2026", Defcon.parsePublic(page))
        assertNull(Defcon.parsePublic("<html>Nothing about it here.</html>"))
        fun light(id: String, lvl: Int) = Indicator(id, id, lvl, "WATCH", "note")
        assertEquals(5, Defcon.estimate(listOf(light("conflict", 0), light("military", 0), light("deploy", 0))).level)
        assertEquals(2, Defcon.estimate(listOf(light("conflict", 3), light("military", 3), light("deploy", 3))).level)
        val p = Defcon.Public(3, "Nov 6, 2026", 1000.0)
        assertEquals(p, Defcon.fromJson(Defcon.toJson(p)))
        assertTrue(!p.old(1000.0 + 3 * 3600) && p.old(1000.0 + 7 * 3600))
    }
}
