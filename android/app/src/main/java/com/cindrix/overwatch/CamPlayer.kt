package com.cindrix.overwatch

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.io.File
import org.videolan.libvlc.LibVLC
import org.videolan.libvlc.Media
import org.videolan.libvlc.MediaPlayer

/** One camera's picture on the phone, played by VLC's video engine. `state` is 'connecting', 'live' or 'offline'; a camera that drops is retried. */
class CamPlayer(ctx: Context, private val camName: String) {
    private val app = ctx.applicationContext
    private val vlc = Vlc.get(app)
    val player = MediaPlayer(vlc)
    var state by mutableStateOf("connecting")
    var recording by mutableStateOf(false)
    private val handler = Handler(Looper.getMainLooper())
    private var url = ""
    private var released = false
    private var recDir: File? = null

    private val giveUp = Runnable { if (state != "live") markOffline() }
    private val retry = Runnable { if (!released && url.isNotEmpty()) start() }

    init {
        player.setEventListener { ev ->
            when (ev.type) {
                MediaPlayer.Event.Playing -> { handler.removeCallbacks(giveUp); state = "live" }
                MediaPlayer.Event.EncounteredError, MediaPlayer.Event.EndReached -> markOffline()
                else -> {}
            }
        }
    }

    private fun markOffline() {
        state = "offline"
        handler.removeCallbacks(retry)
        handler.postDelayed(retry, 8000)
    }

    fun play(address: String, sound: Boolean) {
        url = address
        player.volume = if (sound) 100 else 0
        start()
    }

    private fun start() {
        if (released) return
        state = "connecting"
        val m = Media(vlc, Uri.parse(url))
        m.addOption(":network-caching=400")
        m.addOption(":rtsp-tcp")
        m.addOption(":no-audio-sync")
        player.media = m
        m.release()
        player.play()
        handler.removeCallbacks(giveUp)
        handler.postDelayed(giveUp, 12000)
    }

    fun setSound(on: Boolean) { player.volume = if (on) 100 else 0 }

    /** Starts saving what this camera shows. The file is moved to Documents/Cindrix/Cameras when recording stops. */
    fun startRecord(): Boolean {
        if (state != "live") return false
        val dir = File(app.cacheDir, "rec").apply { mkdirs() }
        recDir = dir
        recording = player.record(dir.absolutePath)
        return recording
    }

    /** Stops recording and files the video. Returns where it went, or null if nothing was recorded. */
    fun stopRecord(): String? {
        if (!recording) return null
        player.record(null)
        recording = false
        val dir = recDir ?: return null
        val files = dir.listFiles()?.filter { it.isFile && it.length() > 0 } ?: return null
        var where: String? = null
        for (f in files) where = Recordings.file(app, f, camName) ?: where
        return where
    }

    fun release() {
        released = true
        handler.removeCallbacksAndMessages(null)
        if (recording) stopRecord()
        try { player.stop() } catch (e: Exception) { /* already stopped */ }
        player.setEventListener(null)
        player.release()
    }
}

object Vlc {
    private var lib: LibVLC? = null
    fun get(ctx: Context): LibVLC = lib ?: LibVLC(ctx.applicationContext, arrayListOf("--no-drop-late-frames", "--no-skip-frames")).also { lib = it }
}

object Recordings {
    private fun safe(name: String) = name.replace(Regex("[\\\\/:*?\"<>|]"), "_").trim().ifEmpty { "Camera" }

    /** Moves a finished recording into the phone's Documents/Cindrix/Cameras/<camera> folder. Returns the folder, or null if it could not. */
    fun file(ctx: Context, f: File, camName: String): String? {
        val rel = "Documents/Cindrix/Cameras/" + safe(camName)
        return try {
            if (Build.VERSION.SDK_INT >= 29) {
                val mime = if (f.extension.equals("ts", true)) "video/mp2t" else "video/mp4"
                val cv = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, f.name)
                    put(MediaStore.MediaColumns.MIME_TYPE, mime)
                    put(MediaStore.MediaColumns.RELATIVE_PATH, rel)
                }
                val uri = ctx.contentResolver.insert(MediaStore.Files.getContentUri("external"), cv) ?: return keep(ctx, f)
                ctx.contentResolver.openOutputStream(uri)?.use { out -> f.inputStream().use { it.copyTo(out) } } ?: return keep(ctx, f)
                f.delete()
                rel
            } else keep(ctx, f)
        } catch (e: Exception) {
            keep(ctx, f)
        }
    }

    /** Fallback: keep it in the app's own folder (older phones). */
    private fun keep(ctx: Context, f: File): String? {
        val dir = File(ctx.getExternalFilesDir(Environment.DIRECTORY_MOVIES), "Cameras").apply { mkdirs() }
        val dest = File(dir, f.name)
        return if (f.renameTo(dest) || (try { f.copyTo(dest, true); f.delete(); true } catch (e: Exception) { false })) dir.absolutePath else null
    }
}
