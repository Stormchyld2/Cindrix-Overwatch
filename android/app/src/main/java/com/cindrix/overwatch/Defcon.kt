package com.cindrix.overwatch

import org.json.JSONObject

/**
 * The DEFCON figure in the header. Two readings, always labelled apart: the Overwatch estimate (from the status lights) and the
 * public tracker at defconlevel.com (itself an estimate; the real level is classified). Neither is official.
 * The estimate never says DEFCON 1: only the public tracker could.
 */
object Defcon {
    const val URL = "https://www.defconlevel.com/"
    const val STALE_HOURS = 6
    val WORDS = mapOf(5 to "Lowest readiness", 4 to "Increased intelligence watch", 3 to "Increase in force readiness",
        2 to "Next step to war", 1 to "Maximum readiness")

    /** (level, exercise name, what it means, readiness): the commonly cited public summary, not the text of an official order. */
    data class Level(val level: Int, val name: String, val means: String, val readiness: String)
    val LEVELS = listOf(
        Level(5, "Fade Out", "Lowest state of readiness", "Normal peacetime readiness"),
        Level(4, "Double Take", "Increased intelligence watch and strengthened security", "Above normal readiness"),
        Level(3, "Round House", "Force readiness raised above normal", "Air Force ready to mobilize in 15 minutes"),
        Level(2, "Fast Pace", "Next step to nuclear war", "Forces ready to deploy and engage in under six hours"),
        Level(1, "Cocked Pistol", "Nuclear war imminent or already begun", "Maximum readiness, immediate response"),
    )
    const val GUIDE_INTRO = "DEFCON (defense readiness condition) is the five-step scale the US military uses to set how ready its forces are for war. " +
        "It counts down: 5 is normal peacetime, 1 is the most severe."
    const val GUIDE_NOTE = "The US has never declared DEFCON 1. The highest level on record is DEFCON 2, for Strategic Air Command in October 1962. " +
        "The current level is never announced, so any live number, including Overwatch's, is an estimate and not an official figure."

    data class Public(val level: Int, val updated: String, val fetched: Double) {
        fun old(now: Double) = fetched <= 0 || now - fetched > STALE_HOURS * 3600
    }

    data class Estimate(val level: Int, val score: Double, val reasons: List<String>)

    private fun plain(s: String) = s.replace(Regex("<[^>]+>"), " ").replace("&middot;", "·").replace("&nbsp;", " ").replace("&amp;", "&")
        .replace(Regex("\\s+"), " ")

    /** (level, update text) from the tracker's home page, or null when it is not there. */
    fun parsePublic(text: String): Pair<Int, String>? {
        val p = plain(text)
        val m = Regex("OSINT\\s+Estimate:\\s*DEFCON\\s*([1-5])\\b", RegexOption.IGNORE_CASE).find(p)
            ?: Regex("\\bDEFCON\\s*([1-5])\\b", RegexOption.IGNORE_CASE).find(p) ?: return null
        val u = Regex("Updated\\s+([A-Z][a-z]{2,8}\\.?\\s+\\d{1,2},\\s+\\d{4})").find(p)?.groupValues?.get(1) ?: ""
        return m.groupValues[1].toInt() to u
    }

    fun estimate(ind: List<Indicator>): Estimate {
        val by = ind.associateBy { it.id }
        var score = 0.0
        val reasons = ArrayList<String>()
        for ((key, w) in listOf("conflict" to 1.0, "military" to 1.0, "deploy" to 1.5)) {
            val r = by[key] ?: continue
            score += w * r.level
            reasons += "${r.label}: ${r.word.lowercase().replaceFirstChar { it.uppercase() }} (${r.note})"
        }
        val level = if (score < 2) 5 else if (score < 4.5) 4 else if (score < 7) 3 else 2
        return Estimate(level, Math.round(score * 10) / 10.0, reasons)
    }

    fun toJson(p: Public): String = JSONObject().put("level", p.level).put("updated", p.updated).put("fetched", p.fetched).toString()

    fun fromJson(s: String): Public? = try {
        val o = JSONObject(s)
        val l = o.getInt("level")
        if (l in 1..5) Public(l, o.optString("updated"), o.getDouble("fetched")) else null
    } catch (e: Exception) { null }
}
