package com.cindrix.overwatch

import android.content.Context
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import org.json.JSONArray

/** One land outline ring as interleaved lon, lat. */
class Ring(val pts: FloatArray, val minLon: Float, val maxLon: Float, val minLat: Float, val maxLat: Float)

fun loadLand(ctx: Context): List<Ring> = try {
    val arr = JSONArray(ctx.assets.open("land.json").bufferedReader().readText())
    (0 until arr.length()).map { i ->
        val r = arr.getJSONArray(i)
        val f = FloatArray(r.length() * 2)
        var mnLo = 999f; var mxLo = -999f; var mnLa = 999f; var mxLa = -999f
        for (k in 0 until r.length()) {
            val p = r.getJSONArray(k)
            val lo = p.getDouble(0).toFloat(); val la = p.getDouble(1).toFloat()
            f[k * 2] = lo; f[k * 2 + 1] = la
            if (lo < mnLo) mnLo = lo; if (lo > mxLo) mxLo = lo; if (la < mnLa) mnLa = la; if (la > mxLa) mxLa = la
        }
        Ring(f, mnLo, mxLo, mnLa, mxLa)
    }
} catch (e: Exception) {
    emptyList()
}

/** Equirectangular camera: x = longitude, y = latitude, centred on (lon0, lat0). Pixels per degree = scale. */
@Stable
class MapCamera {
    var w by mutableFloatStateOf(800f)
    var h by mutableFloatStateOf(400f)
    var lon0 by mutableFloatStateOf(0f)
    var lat0 by mutableFloatStateOf(15f)
    var scale by mutableFloatStateOf(2f)
    private var fitted by mutableStateOf(false)

    fun minScale() = maxOf(w / 360f, h / 180f, 0.5f)

    fun resize(width: Float, height: Float) {
        w = maxOf(width, 50f); h = maxOf(height, 50f)
        if (!fitted) { scale = minScale(); fitted = true }
        scale = maxOf(scale, minScale())
        clamp()
    }

    fun x(lon: Double) = w / 2 + (lon.toFloat() - lon0) * scale
    fun y(lat: Double) = h / 2 - (lat.toFloat() - lat0) * scale

    fun clamp() {
        val halfLon = w / 2 / scale
        val halfLat = h / 2 / scale
        lon0 = if (halfLon < 180) lon0.coerceIn(-180 + halfLon, 180 - halfLon) else 0f
        lat0 = if (halfLat < 90) lat0.coerceIn(-90 + halfLat, 90 - halfLat) else 0f
    }

    fun zoomAt(cx: Float, cy: Float, factor: Float) {
        val lon = lon0 + (cx - w / 2) / scale
        val lat = lat0 - (cy - h / 2) / scale
        scale = (scale * factor).coerceIn(minScale(), 60f)
        lon0 = lon - (cx - w / 2) / scale
        lat0 = lat + (cy - h / 2) / scale
        clamp()
    }

    fun pan(dx: Float, dy: Float) { lon0 -= dx / scale; lat0 += dy / scale; clamp() }

    fun centerOn(lat: Double, lon: Double) {
        scale = maxOf(scale, 4f)
        lat0 = lat.toFloat(); lon0 = lon.toFloat()
        clamp()
    }

    fun reset() { scale = minScale(); lon0 = 0f; lat0 = 15f; clamp() }
}

fun layerOf(k: Kind): Kind = when (k) { Kind.HAZARD, Kind.WEATHER, Kind.SPACE, Kind.HEALTH -> Kind.HAZARD; else -> k }

@Composable
fun WorldMap(vm: OverwatchViewModel, cam: MapCamera, modifier: Modifier = Modifier) {
    val ctx = LocalContext.current
    val land = remember { loadLand(ctx) }
    val pins = vm.items.filter { it.pinned && layerOf(it.kind) in vm.layers }
    val sel = vm.selected
    val centre = vm.centerOn
    LaunchedEffect(centre) {
        if (centre != null && centre.pinned) { cam.centerOn(centre.lat!!, centre.lon!!); vm.centerOn = null }
    }
    Canvas(
        modifier = modifier
            .fillMaxSize()
            .onSizeChanged { cam.resize(it.width.toFloat(), it.height.toFloat()) }
            .pointerInput(Unit) {
                detectTransformGestures { centroid, pan, zoom, _ ->
                    if (zoom != 1f) cam.zoomAt(centroid.x, centroid.y, zoom)
                    cam.pan(pan.x, pan.y)
                }
            }
            .pointerInput(pins) {
                detectTapGestures(
                    onTap = { off ->
                        var best: Item? = null
                        var bd = 28f * 28f
                        for (p in pins) {
                            val dx = cam.x(p.lon!!) - off.x
                            val dy = cam.y(p.lat!!) - off.y
                            val d = dx * dx + dy * dy
                            if (d <= bd) { best = p; bd = d }
                        }
                        vm.select(best)
                    },
                    onDoubleTap = { off -> cam.zoomAt(off.x, off.y, 1.8f) },
                )
            },
    ) {
        drawRect(Ow.MapBg)
        // graticule every 30 degrees
        for (lon in -180..180 step 30) drawLine(Ow.Panel, Offset(cam.x(lon.toDouble()), 0f), Offset(cam.x(lon.toDouble()), size.height), 1f)
        for (lat in -90..90 step 30) drawLine(Ow.Panel, Offset(0f, cam.y(lat.toDouble())), Offset(size.width, cam.y(lat.toDouble())), 1f)
        for (r in land) {
            val left = cam.x(r.minLon.toDouble()); val right = cam.x(r.maxLon.toDouble())
            val top = cam.y(r.maxLat.toDouble()); val bottom = cam.y(r.minLat.toDouble())
            if (right < 0 || left > size.width || bottom < 0 || top > size.height) continue
            val path = Path()
            var k = 0
            while (k < r.pts.size) {
                val px = cam.x(r.pts[k].toDouble()); val py = cam.y(r.pts[k + 1].toDouble())
                if (k == 0) path.moveTo(px, py) else path.lineTo(px, py)
                k += 2
            }
            path.close()
            drawPath(path, Ow.Land)
            drawPath(path, Ow.Outline, style = Stroke(width = 1f))
        }
        for (p in pins) pin(p, cam, sel?.uid == p.uid)
        vm.homePoint?.let { (la, lo) ->
            val c = Offset(cam.x(lo), cam.y(la))
            drawCircle(Ow.Blue, 14f, c, style = Stroke(width = 3f))
            drawCircle(Ow.Blue, 5f, c)
        }
    }
}

private fun DrawScope.pin(it: Item, cam: MapCamera, selected: Boolean) {
    val c = Offset(cam.x(it.lon!!), cam.y(it.lat!!))
    if (c.x < -20 || c.y < -20 || c.x > size.width + 20 || c.y > size.height + 20) return
    val col = Ow.kindColor(it.kind)
    val r = 9f + it.severity * 2f
    if (it.kind == Kind.MILITARY) {
        val d = Path().apply { moveTo(c.x, c.y - r); lineTo(c.x + r, c.y); lineTo(c.x, c.y + r); lineTo(c.x - r, c.y); close() }
        drawPath(d, col)
        drawPath(d, Ow.Charcoal, style = Stroke(width = 2f))
    } else {
        if (it.severity >= 2) drawCircle(col.copy(alpha = 0.3f), r + 9f, c)
        drawCircle(col, r, c)
        drawCircle(Ow.Charcoal, r, c, style = Stroke(width = 2f))
    }
    if (selected) drawCircle(Ow.Bone, r + 12f, c, style = Stroke(width = 3f))
}
