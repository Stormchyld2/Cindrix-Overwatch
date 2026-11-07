package com.cindrix.overwatch

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri

/** One CSV cell, quoted so commas, quotes and line breaks in a name or address cannot break the row. */
fun csvCell(s: String): String = "\"" + s.replace("\"", "\"\"") + "\""

/** Every source (built-in and yours) as a CSV that opens in a spreadsheet; same columns as the Windows export. */
fun sourceListCsv(rows: List<SourceStatus>): String {
    val sb = StringBuilder()
    sb.append(listOf("Name", "Group", "Kind", "Trust", "Address", "Format", "Minutes between checks", "Status").joinToString(",") { csvCell(it) }).append("\r\n")
    for (r in rows) {
        val h = r.health
        val status = when {
            !r.enabled -> "turned off"
            h == null -> "not checked yet"
            h.ok -> "working"
            else -> "problem: " + h.error
        }
        sb.append(listOf(r.src.name, r.src.group, r.src.kind.label, r.src.trust.label, r.src.url, r.src.parser, r.src.everyMinutes.toString(), status)
            .joinToString(",") { csvCell(it) }).append("\r\n")
    }
    return sb.toString()
}

/** Hands the source list to any app that takes text (mail, notes, Drive). Nothing is written to storage. */
fun shareSourceList(ctx: Context, rows: List<SourceStatus>) {
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/csv"
        putExtra(Intent.EXTRA_SUBJECT, "Cindrix Overwatch sources")
        putExtra(Intent.EXTRA_TEXT, sourceListCsv(rows))
    }
    ctx.startActivity(Intent.createChooser(send, "Share source list").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}

private val BASE32 = Regex("^[a-z2-7]{56}$")

/**
 * Turns what was typed or pasted into an address Tor Browser can open, or returns null. Only version 3 onion
 * addresses (56 letters and digits) are accepted, so a half-typed or old-style address is refused before it is opened.
 */
fun onionUrl(text: String): String? {
    var t = text.trim().lowercase()
    if (t.isEmpty()) return null
    t = t.removePrefix("http://").removePrefix("https://")
    val host = t.substringBefore('/').substringBefore('?').substringBefore('#')
    if (!host.endsWith(".onion")) return null
    val label = host.removeSuffix(".onion").substringAfterLast('.')
    if (!BASE32.matches(label)) return null
    // onion services use plain http: the Tor network itself is the encryption
    return "http://" + t
}

private val TOR_BROWSERS = listOf("org.torproject.torbrowser", "org.torproject.torbrowser_alpha")

/** Opens an onion address in Tor Browser for Android. Returns a plain-words problem, or null when it was handed over. */
fun openWithTor(ctx: Context, typed: String): String? {
    val url = onionUrl(typed) ?: return "That is not a full onion address. It needs 56 letters and digits followed by .onion."
    for (pkg in TOR_BROWSERS) {
        val i = Intent(Intent.ACTION_VIEW, Uri.parse(url)).setPackage(pkg).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            ctx.startActivity(i)
            return null
        } catch (_: ActivityNotFoundException) {
        }
    }
    return "Tor Browser is not installed on this phone. Install Tor Browser (from the Tor Project or F-Droid), then try again."
}
