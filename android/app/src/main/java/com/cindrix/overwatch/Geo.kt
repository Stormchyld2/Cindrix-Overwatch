package com.cindrix.overwatch

import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

data class Place(val name: String, val lat: Double, val lon: Double)
data class StateInfo(val code: String, val name: String, val lat: Double, val lon: Double)

/**
 * Finds a place named in a headline so an item can be pinned. Only places named in the text match; the country of the
 * publisher is never used. No match means no pin. Built from places.tsv and states.tsv (same data as the Windows app).
 */
class Gazetteer(placesTsv: String, statesTsv: String) {
    val states: Map<String, StateInfo> = statesTsv.lines().filter { it.isNotBlank() }.associate {
        val f = it.split("\t")
        f[0] to StateInfo(f[0], f[1], f[2].toDouble(), f[3].toDouble())
    }
    private val placeRes: List<Pair<Regex, Place>> = placesTsv.lines().filter { it.isNotBlank() }.map {
        val f = it.split("\t")
        val shown = f[0].substringBefore(" (")
        val opts = if (f[0].length > 4) setOf(RegexOption.IGNORE_CASE) else emptySet()
        Regex("\\b" + Regex.escape(shown) + "\\b", opts) to Place(shown, f[1].toDouble(), f[2].toDouble())
    }
    private val stateRes: List<Pair<Regex, StateInfo>> = (states.values
        .filter { it.name != "Washington State" && it.name != "Georgia (US)" }
        .map { Regex("\\b" + Regex.escape(it.name) + "\\b") to it } +
        listOf(Regex("\\b(WV|W\\.Va\\.)(?![A-Za-z])") to states.getValue("WV")))
        .sortedByDescending { it.second.name.length }

    private fun scanStates(text: String): List<StateInfo> {
        var work = text
        val found = mutableListOf<StateInfo>()
        for ((rx, st) in stateRes) {
            if (rx.containsMatchIn(work)) {
                if (st !in found) found += st
                work = rx.replace(work, " ")
            }
        }
        return found
    }

    fun findPlace(text: String): Place? {
        var best: Place? = null
        var bestLen = 0
        for ((rx, p) in placeRes) {
            val m = rx.find(text) ?: continue
            if (m.value.length > bestLen) {
                best = p
                bestLen = m.value.length
            }
        }
        if (best != null) return best
        val st = scanStates(text).firstOrNull() ?: return null
        return Place(st.name, st.lat, st.lon)
    }

    fun findStates(text: String): List<String> = scanStates(text).map { it.code }.sorted()

    fun homePoint(codes: List<String>): Pair<Double, Double>? {
        val pts = codes.mapNotNull { states[it] }
        if (pts.isEmpty()) return null
        return pts.sumOf { it.lat } / pts.size to pts.sumOf { it.lon } / pts.size
    }
}

fun haversineKm(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val r = 6371.0
    val p1 = Math.toRadians(lat1)
    val p2 = Math.toRadians(lat2)
    val dp = p2 - p1
    val dl = Math.toRadians(lon2 - lon1)
    val a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
    return 2 * r * asin(sqrt(a))
}

/** Rough world regions for the Intel filters, based on where a story is pinned. A story that is not on the map has no region. */
val REGIONS = listOf("Americas", "Europe", "Middle East", "Africa", "Asia-Pacific")

fun regionOf(lat: Double, lon: Double): String = when {
    lon in -170.0..-30.0 -> "Americas"
    lat in 12.0..42.0 && lon in 34.0..63.0 -> "Middle East"
    lat >= 35.0 && lon in -25.0..45.0 -> "Europe"
    lat >= -35.0 && lat < 35.0 && lon in -20.0..55.0 -> "Africa"
    else -> "Asia-Pacific"
}
