package com.cindrix.overwatch

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

/**
 * The optional AI on the phone. A phone cannot run the model, so Overwatch asks a model server you run yourself
 * (the same llama-server the Windows app starts, or any server that speaks the same chat protocol) at an address
 * you type in. It is only ever called when you have set that address, and only on your own network or over https.
 * It is used only to name the place a story is about; the brief and the translation never use it.
 */
class AiError(message: String) : Exception(message)

/** Returns the cleaned server address, or null. http is allowed only for addresses on your own network. */
fun validAiUrl(text: String?): String? {
    var t = (text ?: "").trim().trimEnd('/')
    if (t.isEmpty()) return null
    if (!t.contains("://")) t = "http://$t"
    return try {
        val u = URI(t)
        val host = (u.host ?: return null).lowercase()
        if (u.rawPath.orEmpty().isNotEmpty() || u.rawQuery != null) return null
        when (u.scheme) {
            "https" -> if (host.contains('.') || host == "localhost") t else null
            "http" -> if (isLocalHost(host)) t else null
            else -> null
        }
    } catch (e: Exception) {
        null
    }
}

fun isLocalHost(host: String): Boolean {
    if (host == "localhost" || host.endsWith(".local")) return true
    val p = host.split(".")
    if (p.size != 4) return false
    val n = p.map { it.toIntOrNull() ?: return false }
    if (n.any { it !in 0..255 }) return false
    return n[0] == 10 || n[0] == 127 || (n[0] == 192 && n[1] == 168) || (n[0] == 172 && n[1] in 16..31) || (n[0] == 100 && n[1] in 64..127)
}

class AiClient(private val base: String) {
    fun chat(system: String, user: String, maxTokens: Int = 700, temperature: Double = 0.3, extra: JSONObject? = null): String {
        val msgs = JSONArray()
        if (system.isNotEmpty()) msgs.put(JSONObject().put("role", "system").put("content", system))
        msgs.put(JSONObject().put("role", "user").put("content", user))
        val body = JSONObject().put("model", "cindrix").put("stream", false).put("temperature", temperature).put("top_k", 40)
            .put("min_p", 0.08).put("repeat_penalty", 1.05).put("max_tokens", maxTokens)
            .put("chat_template_kwargs", JSONObject().put("enable_thinking", false)).put("messages", msgs)
        extra?.keys()?.forEach { k -> body.put(k, extra.get(k)) }
        var conn: HttpURLConnection? = null
        try {
            conn = (URL("$base/v1/chat/completions").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 10_000
                readTimeout = 600_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            if (conn.responseCode != 200) throw AiError("The AI server answered with an error (HTTP ${conn.responseCode}).")
            val text = conn.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
            val content = JSONObject(text).optJSONArray("choices")?.optJSONObject(0)?.optJSONObject("message")?.optString("content") ?: ""
            return Regex("<think>.*?</think>", RegexOption.DOT_MATCHES_ALL).replace(content, "").trim()
        } catch (e: AiError) {
            throw e
        } catch (e: Exception) {
            throw AiError("The AI server did not answer. Check the address in Settings and that the server is running.")
        } finally {
            conn?.disconnect()
        }
    }
}

// ----- keeping feed text from steering the model -----
private val INJECT = Regex("(ignore|disregard|forget)\\s+(all\\s+|any\\s+|the\\s+)?(previous|prior|above|earlier)\\b[^.\\n]*|" +
    "\\b(system|assistant|developer)\\s*:|<\\|[^>]*\\|>|</?\\s*(system|assistant|user)\\s*>|" +
    "\\byou\\s+are\\s+now\\b[^.\\n]*|\\bnew\\s+instructions?\\b[^.\\n]*", RegexOption.IGNORE_CASE)

fun sanitizeHeadline(text: String?, limit: Int = 220): String {
    var t = (text ?: "").replace(Regex("[\\u0000-\\u001f\\u007f]"), " ")
    t = INJECT.replace(t, " ")
    t = t.replace(Regex("[`\\[\\]{}<>]"), "")
    return t.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ").take(limit)
}

// ----- translation -----
private val EN_WORDS = ("the of and to in is for on that with as at by from are was has have will after over new says say amid " +
    "against into its his her their be been not but more than us it an or this these those near over under " +
    "killed attack attacks war troops military").split(" ").toSet()
private val OTHER_WORDS = ("""el la los las del en y que por con para una es se su al lo como más pero sus le les des du et est pour dans sur
avec qui au aux ce cette sont ont pas plus der die das und ist nicht mit von zu auf für ein eine den dem im auch sich
dass wird wurden o os as do da dos das em não uma são foi nos nas num il di che per con è nel della sono anche gli
een het van op te voor zijn niet naar och att som på av för det är har inte ett till en med de""").split(Regex("\\s+")).toSet() - EN_WORDS

/** Guesses whether a headline is not English from letters and common words. Leans toward "English" when unsure. */
fun looksForeign(text: String?): Boolean {
    val t = text ?: ""
    val letters = t.filter { it.isLetter() }
    if (letters.length < 8) return false
    if (letters.count { it.code > 0x24F }.toDouble() / letters.length > 0.3) return true
    val words = Regex("\\p{L}+").findAll(t.lowercase()).map { it.value }.toList()
    val en = words.count { it in EN_WORDS }
    val other = words.count { it in OTHER_WORDS }
    val accents = letters.count { it.code in 0xC0..0x24F }
    if (other >= 2 && other > en) return true
    return other >= 1 && en == 0 && accents >= 1
}

/** Keeps a translation only if it looks like one: one short line, not an answer to the headline, not still foreign. */
fun cleanTranslation(out: String?, original: String): String {
    val t = (out ?: "").trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ").trim('"', '\'', '“', '”', '«', '»', ' ')
    if (t.isEmpty() || t.length > maxOf(60, 4 * original.length)) return ""
    if (Regex("^(translation|here is|here's|sure|certainly)\\b", RegexOption.IGNORE_CASE).containsMatchIn(t) || looksForeign(t)) return ""
    return t.take(300)
}

// ----- map pins -----
const val PIN_SYSTEM = "You say where a news headline takes place. Use only a real place the headline names or clearly means " +
    "(a government's statement belongs to its capital). Never guess. If there is no clear place, say none."

fun parsePlaces(text: String?, count: Int): Map<Int, String> {
    val out = LinkedHashMap<Int, String>()
    for (line in (text ?: "").lines()) {
        val m = Regex("^\\s*(\\d{1,3})\\s*[:.)-]\\s*(.+?)\\s*$").find(line) ?: continue
        val n = m.groupValues[1].toInt()
        val place = m.groupValues[2].trim(' ', '*', '_', '`', '"', '\'')
        if (n in 1..count && place.isNotEmpty() && !Regex("^(none|unknown|n/?a|no clear place)\\b", RegexOption.IGNORE_CASE).containsMatchIn(place) && place.length <= 80) {
            out.putIfAbsent(n, place)
        }
    }
    return out
}
