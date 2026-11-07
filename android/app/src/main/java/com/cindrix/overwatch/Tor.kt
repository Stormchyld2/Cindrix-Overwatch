package com.cindrix.overwatch

import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.Socket
import java.net.URI
import java.net.URL
import java.util.zip.GZIPInputStream

/**
 * Reading onion feeds. Overwatch does not carry its own Tor. It uses the Tor already running on the phone (Orbot, or any
 * app that offers a Tor proxy on port 9050 or 9150). The address is handed to Tor to resolve, never looked up by the phone.
 * This reads public feeds and pages; it is not Tor Browser and does not give browser-level protection.
 */
object Tor {
    private val ONION = Regex("^[a-z2-7]{56}\\.onion$")
    val PORTS = listOf(9050, 9150)

    fun isOnionHost(host: String?) = host != null && ONION.matches(host.lowercase())

    fun isOnionUrl(url: String?): Boolean = try {
        val u = URI((url ?: "").trim())
        (u.scheme == "http" || u.scheme == "https") && isOnionHost(u.host)
    } catch (e: Exception) { false }

    private fun probe(port: Int): Boolean = try {
        Socket().use { it.connect(InetSocketAddress("127.0.0.1", port), 400); true }
    } catch (e: Exception) { false }

    /** The port of a Tor proxy on this phone, or null when none is running. */
    fun proxyPort(): Int? = PORTS.firstOrNull { probe(it) }

    const val NOT_RUNNING = "Tor is not running. Open Orbot (or another Tor app), connect it, then refresh."

    fun fetch(url: String): Pair<Int, String> {
        val port = proxyPort() ?: return 0 to NOT_RUNNING
        val proxy = Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", port))
        var target = url
        for (hop in 0..4) {
            var conn: HttpURLConnection? = null
            try {
                conn = (URL(target).openConnection(proxy) as HttpURLConnection).apply {
                    connectTimeout = 45_000
                    readTimeout = 60_000
                    instanceFollowRedirects = false
                    setRequestProperty("User-Agent", USER_AGENT)
                    setRequestProperty("Accept", "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html, */*;q=0.8")
                }
                val code = conn.responseCode
                if (code in 300..399) {
                    val loc = conn.getHeaderField("Location") ?: return code to ""
                    val next = URL(URL(target), loc).toString()
                    if (!isOnionUrl(next)) return 0 to "It redirected away from Tor, which was refused."
                    target = next
                    continue
                }
                if (code != 200) return code to ""
                val buf = ByteArrayOutputStream()
                conn.inputStream.use { s ->
                    val tmp = ByteArray(16_384)
                    while (buf.size() < MAX_BYTES) {
                        val n = s.read(tmp)
                        if (n < 0) break
                        buf.write(tmp, 0, n)
                    }
                }
                var bytes = buf.toByteArray()
                if (bytes.size > 2 && bytes[0] == 0x1f.toByte() && bytes[1] == 0x8b.toByte()) {
                    bytes = GZIPInputStream(bytes.inputStream()).use { it.readBytes() }
                }
                return 200 to String(bytes, Charsets.UTF_8)
            } catch (e: Exception) {
                return 0 to "Tor could not reach it (${(e.message ?: e.javaClass.simpleName).take(80)})"
            } finally {
                conn?.disconnect()
            }
        }
        return 0 to "Too many redirects."
    }
}
