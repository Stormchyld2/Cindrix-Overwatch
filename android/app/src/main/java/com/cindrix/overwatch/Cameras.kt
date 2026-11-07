package com.cindrix.overwatch

import java.net.URLDecoder
import java.net.URLEncoder
import java.util.UUID
import org.json.JSONObject

/** IP cameras: the list of supported makes and building a stream address from what the person types. Mirrors cindrix_overwatch/cameras.py. */

class CameraError(message: String) : Exception(message)

data class Brand(
    val id: String, val name: String, val tier: String, val port: Int, val scheme: String,
    val main: String, val sub: String, val models: String, val note: String, val setup: String,
)

data class Suggestion(val name: String, val note: String)
data class SuggestionGroup(val name: String, val items: List<Suggestion>)

data class Catalog(
    val about: String, val tiers: Map<String, String>, val brands: List<Brand>,
    val suggestTitle: String = "", val suggestAbout: String = "", val suggestions: List<SuggestionGroup> = emptyList(),
) {
    fun brand(id: String): Brand? = brands.firstOrNull { it.id == id }
}

data class Camera(
    val id: String, val name: String, val brand: String, val main: String, val sub: String,
    val user: String, val password: String, val enabled: Boolean,
)

object Cameras {
    private val SCHEMES = setOf("rtsp", "rtsps", "http", "https")
    private val WHOLE = Regex("^[a-z][a-z0-9+.-]*://", RegexOption.IGNORE_CASE)
    private val URL = Regex("^([a-z][a-z0-9+.-]*)://(?:([^:@/]*)(?::([^@/]*))?@)?(\\[[^\\]]+\\]|[^:/?#]+)(?::(\\d+))?(.*)$", RegexOption.IGNORE_CASE)

    fun parseCatalog(text: String): Catalog {
        val o = JSONObject(text)
        val t = o.getJSONObject("tiers")
        val tiers = t.keys().asSequence().associateWith { t.getString(it) }
        val arr = o.getJSONArray("brands")
        val brands = (0 until arr.length()).map { i ->
            val b = arr.getJSONObject(i)
            Brand(b.getString("id"), b.getString("name"), b.getString("tier"), b.optInt("port", 554), b.optString("scheme", "rtsp"),
                b.optString("main"), b.optString("sub"), b.optString("models"), b.optString("note"), b.optString("setup"))
        }
        val sg = o.optJSONObject("suggestions")
        val groups = sg?.optJSONArray("groups")?.let { ga ->
            (0 until ga.length()).map { i ->
                val g = ga.getJSONObject(i)
                val ia = g.getJSONArray("items")
                SuggestionGroup(g.getString("name"), (0 until ia.length()).map { j -> ia.getJSONObject(j).let { Suggestion(it.getString("name"), it.getString("note")) } })
            }
        } ?: emptyList()
        return Catalog(o.optString("about"), tiers, brands, sg?.optString("title") ?: "", sg?.optString("about") ?: "", groups)
    }

    private fun dec(s: String) = URLDecoder.decode(s.replace("+", "%2B"), "UTF-8")
    fun enc(s: String) = URLEncoder.encode(s, "UTF-8").replace("+", "%20")

    private data class Parts(val scheme: String, val user: String?, val pass: String?, val host: String, val port: String?, val rest: String)

    private fun parts(url: String): Parts? = URL.matchEntire(url.trim())?.let {
        Parts(it.groupValues[1].lowercase(), it.groups[2]?.value, it.groups[3]?.value, it.groupValues[4], it.groups[5]?.value, it.groupValues[6])
    }

    /** Pulls user:password out of an address that has them, so they are stored apart and never shown. */
    fun splitAuth(url: String): Triple<String, String, String> {
        val p = parts(url) ?: return Triple(url, "", "")
        if (p.user == null) return Triple(url, "", "")
        val clean = "${p.scheme}://${p.host}" + (p.port?.let { ":$it" } ?: "") + p.rest
        return Triple(clean, dec(p.user), dec(p.pass ?: ""))
    }

    fun validAddress(url: String): Boolean {
        val t = url.trim()
        val p = parts(t) ?: return false
        return p.scheme in SCHEMES && p.host.isNotEmpty() && !t.contains(' ')
    }

    /** The address without a password. `host` can be an IP, a name, or a whole address; a whole address is used as typed. */
    fun buildAddress(cat: Catalog, brandId: String, hostIn: String, port: String? = null, stream: String = "main", pathOverride: String = ""): String {
        var host = hostIn.trim()
        if (WHOLE.containsMatchIn(host)) return splitAuth(host).first
        val b = cat.brand(brandId)
        val path = pathOverride.ifEmpty { (if (stream == "main") b?.main else b?.sub) ?: "" }
        if (path.isEmpty()) return ""
        val portNum = port?.takeIf { it.isNotBlank() }?.toInt() ?: (b?.port ?: 554)
        val scheme = b?.scheme?.ifEmpty { "rtsp" } ?: "rtsp"
        if (host.contains(":") && !host.startsWith("[")) host = "[$host]"
        return "$scheme://$host:$portNum" + (if (path.startsWith("/")) path else "/$path")
    }

    fun newCamera(cat: Catalog, name: String, brandId: String, hostIn: String, user: String = "", password: String = "", port: String? = null, subHost: String = ""): Camera {
        val nm = name.trim().take(60).ifEmpty { "Camera" }
        var host = hostIn.trim()
        if (host.isEmpty()) throw CameraError("Type the camera's address. It is on the camera's label, in its app, or in your router's list of devices.")
        var u = user
        var pw = password
        val whole = WHOLE.containsMatchIn(host)
        if (whole) {
            val (clean, au, ap) = splitAuth(host)
            host = clean
            if (u.isEmpty()) u = au
            if (pw.isEmpty()) pw = ap
        }
        if (!port.isNullOrBlank() && !(port.all { it.isDigit() } && port.toInt() in 1..65535)) throw CameraError("The port must be a number from 1 to 65535.")
        val main = buildAddress(cat, brandId, host, port, "main")
        if (main.isEmpty()) throw CameraError("This make has no standard address. Paste the camera's whole address (it starts with rtsp:// or http://).")
        if (!validAddress(main)) throw CameraError("That is not a usable camera address. It should look like 192.168.1.50 or rtsp://192.168.1.50:554/stream1.")
        var sub = ""
        if (subHost.isNotBlank()) {
            sub = buildAddress(cat, brandId, subHost, port, "sub")
            if (sub.isNotEmpty() && !validAddress(sub)) throw CameraError("The sub-stream address is not usable.")
        } else if (!whole) {
            sub = buildAddress(cat, brandId, host, port, "sub")
        }
        return Camera(UUID.randomUUID().toString().take(8), nm, brandId.ifEmpty { "other" }, main, sub, u.trim(), pw, true)
    }

    /** The address to play, with the login put back in. Falls back to the main stream when there is no sub-stream. */
    fun streamAddress(cam: Camera, sub: Boolean = false): String {
        val url = (if (sub) cam.sub else "").ifEmpty { cam.main }
        if (cam.user.isEmpty() && cam.password.isEmpty()) return url
        val p = parts(url) ?: return url
        return "${p.scheme}://${enc(cam.user)}:${enc(cam.password)}@${p.host}" + (p.port?.let { ":$it" } ?: "") + p.rest
    }

    /** The address for the screen: never includes the password. */
    fun shownAddress(cam: Camera): String = cam.main
}
