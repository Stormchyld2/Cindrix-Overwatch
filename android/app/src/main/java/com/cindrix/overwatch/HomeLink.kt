package com.cindrix.overwatch

import android.content.Context
import android.net.VpnService
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import java.io.ByteArrayInputStream
import java.net.HttpURLConnection
import java.net.URL

/** The phone's built-in connection to the home PC. It joins the same CindrixVPN server as the PC (WireGuard), only for Overwatch's own traffic. */
object HomeLink {
    @Volatile var up = false
    private var backend: GoBackend? = null

    private val tunnel = object : Tunnel {
        override fun getName() = "overwatch"
        override fun onStateChange(newState: Tunnel.State) { up = newState == Tunnel.State.UP }
    }

    /** Null when Android already allows the VPN; otherwise the intent that asks the person once. */
    fun consentIntent(ctx: Context) = VpnService.prepare(ctx)

    /** Starts the tunnel. Returns null when it is up, or a plain-words problem. Runs on a background thread. */
    fun bringUp(ctx: Context, conf: String): String? = try {
        val b = backend ?: GoBackend(ctx.applicationContext).also { backend = it }
        b.setState(tunnel, Tunnel.State.UP, Config.parse(ByteArrayInputStream(conf.toByteArray())))
        up = true
        null
    } catch (e: Exception) {
        "The VPN would not start: " + (e.message ?: "unknown problem")
    }

    fun bringDown(ctx: Context) {
        try {
            backend?.setState(tunnel, Tunnel.State.DOWN, null)
        } catch (e: Exception) {
            // already down
        }
        up = false
    }

    private fun get(host: String, port: Int, path: String, timeoutMs: Int): String? = try {
        val c = URL("http://$host:$port$path").openConnection() as HttpURLConnection
        c.connectTimeout = timeoutMs
        c.readTimeout = timeoutMs + 2000
        try { if (c.responseCode == 200) c.inputStream.bufferedReader().readText() else null } finally { c.disconnect() }
    } catch (e: Exception) {
        null
    }

    /** True when the Overwatch PC answers at this address. */
    fun hello(host: String, port: Int, timeoutMs: Int = 1500): Boolean = get(host, port, "/v1/hello", timeoutMs)?.contains("overwatch") == true

    fun fetchCameras(host: String, port: Int, token: String): List<LinkedCamera>? =
        get(host, port, "/v1/cameras?token=$token", 4000)?.let { try { Link.parseCameras(it) } catch (e: Exception) { null } }

    /** Finds a way to the PC: straight over the home Wi-Fi if it answers, otherwise through the VPN. Returns the host to use, or null. */
    fun reachPc(ctx: Context, code: LinkCode, conf: String?): String? {
        code.lan?.let { if (hello(it, code.port)) return it }
        val vpn = code.vpn ?: return null
        if (conf == null) return null
        if (!up && bringUp(ctx, conf) != null) return null
        repeat(10) {
            if (hello(vpn, code.port)) return vpn
            Thread.sleep(1000)
        }
        return null
    }
}
