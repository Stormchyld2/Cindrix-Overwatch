package com.cindrix.overwatch

/** Turns a web page into plain readable text, with no scripts and no pictures. Used by "Read the article here". */
private val DROP = Regex("<(script|style|noscript|svg|nav|header|footer|aside|form|iframe)\\b[^>]*>.*?</\\1\\s*>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
private val COMMENT = Regex("<!--.*?-->", RegexOption.DOT_MATCHES_ALL)
private val PARA = Regex("<p\\b[^>]*>(.*?)</p\\s*>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
private val BREAKS = Regex("</?(p|div|br|li|h[1-6]|tr|section|article|blockquote)\\b[^>]*>", RegexOption.IGNORE_CASE)
private val TAGS = Regex("<[^>]*>")
private val ENTITY = Regex("&(#x?[0-9a-fA-F]+|[a-zA-Z]+);")

fun decodeEntities(s: String): String = ENTITY.replace(s) { m ->
    val e = m.groupValues[1]
    when {
        e.startsWith("#x") || e.startsWith("#X") -> e.substring(2).toIntOrNull(16)?.takeIf { it in 32..0x10FFFF }?.let { String(Character.toChars(it)) } ?: ""
        e.startsWith("#") -> e.substring(1).toIntOrNull()?.takeIf { it in 32..0x10FFFF }?.let { String(Character.toChars(it)) } ?: ""
        else -> when (e.lowercase()) {
            "amp" -> "&"; "lt" -> "<"; "gt" -> ">"; "quot" -> "\""; "apos" -> "'"; "nbsp" -> " "
            "ndash" -> "–"; "mdash" -> "—"; "rsquo", "lsquo" -> "'"; "ldquo", "rdquo" -> "\""; "hellip" -> "…"
            else -> ""
        }
    }
}

private fun clean(fragment: String): String =
    decodeEntities(TAGS.replace(fragment, " ")).replace(Regex("[ \\t\\u00a0]+"), " ").trim()

/** Plain text of the main part of a page. Prefers real paragraphs; falls back to all visible text. Capped so a huge page cannot flood the screen. */
fun htmlToText(html: String, maxChars: Int = 20_000): String {
    val page = COMMENT.replace(DROP.replace(html, " "), " ")
    val paras = PARA.findAll(page).map { clean(it.groupValues[1]) }.filter { it.length >= 40 }.toList()
    val text = if (paras.size >= 3) paras.joinToString("\n\n") else {
        BREAKS.replace(page, "\n").let { TAGS.replace(it, " ") }.let { decodeEntities(it) }
            .lines().map { it.replace(Regex("[ \\t\\u00a0]+"), " ").trim() }.filter { it.length >= 25 }.joinToString("\n\n")
    }
    return text.take(maxChars)
}
