package com.cindrix.overwatch

/** Sorting items into kinds, grouping the same story, matching to home, and the status lights. Simple counts, no hidden scoring. */
private fun words(vararg w: String) = Regex("\\b(?:" + w.joinToString("|") + ")", RegexOption.IGNORE_CASE)

private val CONFLICT = words("attack", "airstrike", "air strike", "missile", "shelling", "invasion", "offensive", "bombing",
    "drone strike", "hostage", "ceasefire", "shot down", "casualt", "troops", "war\\b", "killed", "clashes", "insurgent", "rebels", "coup")
private val MILITARY = words("navy", "naval", "army", "air force", "marine", "warship", "destroyer", "aircraft carrier", "fighter jet",
    "exercise", "deploy", "nato", "pentagon", "defense ministry", "defence ministry", "submarine", "military", "coast guard",
    "space force", "bomber", "armed forces")
private val HEALTH = words("outbreak", "epidemic", "pandemic", "virus", "cholera", "ebola", "measles", "bird flu", "h5n1", "mpox", "quarantine", "marburg", "dengue")
private val HAZARD = words("earthquake", "tsunami", "hurricane", "typhoon", "cyclone", "wildfire", "flood", "volcano", "tornado", "landslide", "eruption")
private val GRID = words("power outage", "blackout", "power grid", "grid failure", "without power", "power cuts")
private val SUPPLY = words("shortage", "fuel prices", "food prices", "supply chain", "rationing", "panic buying", "price gouging")
private val SEVERE = words("nuclear", "invasion", "mass casualt", "explosion", "killed", "dead\\b", "massacre", "chemical")
private val STOP = ("the and for with from that this have has are was were will after over into about says said new amid more than " +
    "their they its his her who what when where how not but out off one two three").split(" ").toSet()

fun classify(it: Item): Item {
    if (it.kind != Kind.NEWS) return it
    val t = it.title
    when {
        CONFLICT.containsMatchIn(t) -> it.kind = Kind.CONFLICT
        MILITARY.containsMatchIn(t) -> it.kind = Kind.MILITARY
        HEALTH.containsMatchIn(t) -> it.kind = Kind.HEALTH
        HAZARD.containsMatchIn(t) -> it.kind = Kind.HAZARD
    }
    when (it.kind) {
        Kind.CONFLICT -> it.severity = maxOf(it.severity, if (SEVERE.containsMatchIn(t)) 2 else 1)
        Kind.HEALTH, Kind.HAZARD -> it.severity = maxOf(it.severity, 1)
        else -> {}
    }
    return it
}

fun isHome(item: Item, home: List<String>) = item.states.any { it in home }

private fun tokens(title: String): Set<String> =
    Regex("[a-z0-9]+").findAll(title.lowercase()).map { it.value }.filter { it.length > 3 && it !in STOP }.toSet()

private fun rank(i: Item): Double = (when (i.trust) { Trust.OFFICIAL -> 2 else -> if (i.trust == Trust.WIRE) 1 else 0 }) * 1e12 + i.severity * 1e10 + i.ts

/** Collapses reports of the same story into one item with a count. Structured hazard data is left alone. */
fun group(items: List<Item>, windowHours: Int = 48): List<Item> {
    class Cluster(var ts: Double, val toks: MutableSet<String>, val members: MutableList<Item>)
    val out = mutableListOf<Item>()
    val clusters = mutableListOf<Cluster>()
    for (it in items.sortedByDescending { it.ts }) {
        if (it.kind == Kind.HAZARD || it.kind == Kind.WEATHER || it.kind == Kind.SPACE) {
            out += it
            continue
        }
        val toks = tokens(it.title)
        var placed = false
        for (c in clusters) {
            if (Math.abs(c.ts - it.ts) > windowHours * 3600) continue
            val common = toks.intersect(c.toks).size
            val union = toks.union(c.toks).size
            if (toks.isNotEmpty() && c.toks.isNotEmpty() && common >= 3 && common.toDouble() / union >= 0.4) {
                c.members += it
                c.toks += toks
                placed = true
                break
            }
        }
        if (!placed) clusters += Cluster(it.ts, toks.toMutableSet(), mutableListOf(it))
    }
    for (c in clusters) {
        val sources = c.members.map { it.sourceId }.toSet()
        val rep = c.members.maxByOrNull { rank(it) }!!
        rep.count = if (sources.size > 1) sources.size else c.members.size
        out += rep
    }
    return out.sortedByDescending { it.ts }
}

data class Indicator(val id: String, val label: String, val level: Int, val word: String, val note: String)

private fun level(n: Int, vararg cuts: Int) = cuts.count { n >= it }

fun indicators(items: List<Item>, home: List<String>, geo: Gazetteer, now: Double): List<Indicator> {
    val day = items.filter { now - it.ts <= 24 * 3600 }
    val two = items.filter { now - it.ts <= 48 * 3600 }
    val week = items.filter { now - it.ts <= 7 * 24 * 3600 }
    val out = mutableListOf<Indicator>()
    val std = listOf("NORMAL", "WATCH", "ELEVATED", "HIGH")

    val wx = two.filter { it.kind == Kind.WEATHER && isHome(it, home) }
    val wl = wx.maxOfOrNull { it.severity } ?: 0
    out += Indicator("weather", "Home weather", wl, listOf("NORMAL", "ADVISORY", "WARNING", "SEVERE")[wl],
        if (wx.isNotEmpty()) "${wx.size} active alert${if (wx.size != 1) "s" else ""} at home" else "No alerts at home")

    val grid = two.filter { GRID.containsMatchIn(it.title) }
    val gl = level(grid.size, 1, 3, 10)
    out += Indicator("grid", "Power grid", gl, std[gl], if (grid.isNotEmpty()) "${grid.size} outage headlines, 48 h" else "No outage headlines")

    val hp = geo.homePoint(home)
    val near = if (hp == null) emptyList() else week.filter {
        it.sourceId == "usgs" && it.pinned && haversineKm(hp.first, hp.second, it.lat!!, it.lon!!) <= 500
    }
    val ql = if (near.isEmpty()) 0 else minOf(3, (near.maxOf { it.severity }) + 1)
    out += Indicator("quakes", "Quakes near home", ql, listOf("QUIET", "WATCH", "ELEVATED", "HIGH")[ql],
        if (near.isNotEmpty()) "${near.size} within 500 km, 7 days" else if (hp != null) "None within 500 km, 7 days" else "Set a home state")

    val hl = group(week.filter { it.kind == Kind.HEALTH })
    val hlv = level(hl.size, 1, 3, 6)
    out += Indicator("outbreaks", "Outbreaks", hlv, std[hlv], if (hl.isNotEmpty()) "${hl.size} health items, 7 days" else "No new alerts")

    val sp = two.filter { it.kind == Kind.SPACE }
    val sl = sp.maxOfOrNull { it.severity } ?: 0
    out += Indicator("space", "Space weather", sl, listOf("NORMAL", "WATCH", "STORM", "SEVERE")[sl],
        sp.maxByOrNull { it.severity }?.title?.substringBefore(":") ?: "Calm")

    val cf = group(day.filter { it.kind == Kind.CONFLICT })
    val cl = level(cf.size, 5, 15, 30)
    out += Indicator("conflict", "Conflict reporting", cl, std[cl], "${cf.size} stories, 24 h")

    val ml = group(day.filter { it.kind == Kind.MILITARY })
    val mlv = level(ml.size, 5, 15, 30)
    out += Indicator("military", "Military activity", mlv, listOf("QUIET", "ACTIVE", "BUSY", "HIGH")[mlv], "${ml.size} items, 24 h")

    val sup = two.filter { SUPPLY.containsMatchIn(it.title) }
    val sul = level(sup.size, 2, 5, 10)
    out += Indicator("supply", "Supply news", sul, std[sul], if (sup.isNotEmpty()) "${sup.size} headlines, 48 h" else "Nothing unusual")
    return out
}
