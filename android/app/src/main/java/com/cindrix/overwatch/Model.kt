package com.cindrix.overwatch

import java.security.MessageDigest

enum class Kind(val label: String) {
    MILITARY("MILITARY"), CONFLICT("CONFLICT"), HAZARD("HAZARD"), WEATHER("WEATHER"),
    SPACE("SPACE"), HEALTH("HEALTH"), NEWS("NEWS");

    companion object {
        fun of(s: String): Kind = entries.firstOrNull { it.name.equals(s, ignoreCase = true) } ?: NEWS
    }
}

enum class Trust(val label: String) {
    OFFICIAL("Official source"), WIRE("Wire or agency"), OUTLET("Single outlet");

    companion object {
        fun of(s: String): Trust = entries.firstOrNull { it.name.equals(s, ignoreCase = true) } ?: OUTLET
    }
}

val SEVERITY_WORDS = listOf("Info", "Notice", "Warning", "Severe")

/** The one record every source is turned into. Times are epoch seconds. */
class Item(
    val sourceId: String,
    val source: String,
    var kind: Kind,
    val trust: Trust,
    title: String,
    val url: String = "",
    summary: String = "",
    val ts: Double = 0.0,
    var lat: Double? = null,
    var lon: Double? = null,
    var place: String = "",
    severity: Int = 0,
    var states: List<String> = emptyList(),
    uid: String = "",
) {
    val title: String = title.trim().replace(Regex("\\s+"), " ").take(300)
    val summary: String = summary.trim().replace(Regex("\\s+"), " ").take(500)
    var severity: Int = severity.coerceIn(0, 3)
    var count: Int = 1
    var firstSeen: Double = 0.0
    var titleEn: String = ""
    var summaryEn: String = ""
    /** The English title when one was made, else the original. */
    val shown: String get() = titleEn.ifEmpty { title }
    val uid: String = uid.ifEmpty { sha1("$sourceId|${url.ifEmpty { this.title }}").take(20) }
    val pinned: Boolean get() = lat != null && lon != null
}

fun sha1(s: String): String =
    MessageDigest.getInstance("SHA-1").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

class FeedError(message: String) : Exception(message)
