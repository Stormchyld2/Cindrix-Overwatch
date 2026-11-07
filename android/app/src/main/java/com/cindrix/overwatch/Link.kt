package com.cindrix.overwatch

import org.json.JSONObject

/** The phone's end of the link to the home PC: the pairing code, the VPN config, and the cameras the PC hands over.
 *  Everything here is plain logic with no Android calls, so it is tested on the computer. */

data class LinkCode(val lan: String?, val vpn: String?, val port: Int, val token: String)

/** A camera handed over by the PC. The phone builds its address from whichever host it reached the PC on. */
data class LinkedCamera(
    val id: String, val name: String, val brand: String, val port: Int, val user: String, val password: String,
    val mainScheme: String, val mainPath: String, val subScheme: String, val subPath: String,
) {
    fun address(host: String, sub: Boolean = false): String {
        val scheme = (if (sub && subPath.isNotEmpty()) subScheme else mainScheme).ifEmpty { "rtsp" }
        val path = (if (sub && subPath.isNotEmpty()) subPath else mainPath).ifEmpty { "/" }
        val login = if (user.isNotEmpty() || password.isNotEmpty()) "${Cameras.enc(user)}:${Cameras.enc(password)}@" else ""
        return "$scheme://$login$host:$port$path"
    }
}

object Link {
    const val VERSION = "OW1"

    fun parseCode(code: String): LinkCode? {
        val p = code.trim().split("/")
        if (p.size != 5 || p[0] != VERSION) return null
        val port = p[3].toIntOrNull() ?: return null
        if (port !in 1..65535 || p[4].isEmpty() || !p[4].all { it.isLetterOrDigit() }) return null
        return LinkCode(p[1].takeIf { it != "-" }, p[2].takeIf { it != "-" }, port, p[4])
    }

    fun parseCameras(json: String): List<LinkedCamera> {
        val arr = JSONObject(json).getJSONArray("cameras")
        return (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            val m = o.optJSONObject("main")
            val s = o.optJSONObject("sub")
            LinkedCamera(o.getString("id"), o.getString("name"), o.optString("brand", "other"), o.getInt("port"), o.optString("user"), o.optString("password"),
                m?.optString("scheme") ?: "rtsp", m?.optString("path") ?: "/", s?.optString("scheme") ?: "", s?.optString("path") ?: "")
        }
    }

    /** What the person sees about a config they paste: null address means it is not usable. */
    data class WgInfo(val address: String, val endpoint: String)

    private fun lines(text: String) = text.lines().map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }

    private fun value(l: List<String>, key: String): String? =
        l.firstOrNull { it.substringBefore("=").trim().equals(key, ignoreCase = true) }?.substringAfter("=")?.trim()

    /** The network the VPN uses, from the phone's own address: 10.66.66.3/32 gives 10.66.66.0/24. */
    fun subnetOf(address: String): String? {
        val ip = address.substringBefore("/").trim().split(".")
        if (ip.size != 4 || ip.any { it.toIntOrNull() !in 0..255 }) return null
        return "${ip[0]}.${ip[1]}.${ip[2]}.0/24"
    }

    fun wgInfo(text: String): WgInfo? {
        val l = lines(text)
        val addr = value(l, "Address") ?: return null
        val ep = value(l, "Endpoint") ?: return null
        if (value(l, "PrivateKey").isNullOrEmpty() || value(l, "PublicKey").isNullOrEmpty() || subnetOf(addr) == null) return null
        return WgInfo(addr, ep)
    }

    /** Turns the server's ready-made phone config into the one Overwatch uses: only the VPN's own network goes through the tunnel,
     *  only Overwatch uses it, and the phone's other traffic and DNS are left alone. Returns null when the text is not a usable config. */
    fun rewriteWg(text: String, pkg: String): String? {
        val l = lines(text)
        val addr = value(l, "Address") ?: return null
        val net = subnetOf(addr) ?: return null
        val priv = value(l, "PrivateKey")?.takeIf { it.isNotEmpty() } ?: return null
        val pub = value(l, "PublicKey")?.takeIf { it.isNotEmpty() } ?: return null
        val ep = value(l, "Endpoint")?.takeIf { it.isNotEmpty() } ?: return null
        val psk = value(l, "PresharedKey")
        return buildString {
            append("[Interface]\nPrivateKey = $priv\nAddress = $addr\nIncludedApplications = $pkg\n\n")
            append("[Peer]\nPublicKey = $pub\n")
            if (!psk.isNullOrEmpty()) append("PresharedKey = $psk\n")
            append("Endpoint = $ep\nAllowedIPs = $net\nPersistentKeepalive = 25\n")
        }
    }
}
