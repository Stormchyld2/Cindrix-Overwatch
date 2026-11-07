package com.cindrix.overwatch

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.fragment.app.FragmentActivity
import kotlinx.coroutines.delay
import org.videolan.libvlc.util.VLCVideoLayout

/** Holds the player of one tile so the Record button can reach it. */
class TileCtl { var player by mutableStateOf<CamPlayer?>(null) }

/** The Watchtower tab: one camera by default, or four at once. The list of cameras opens from the menu button. */
@Composable
fun WatchtowerScreen(vm: OverwatchViewModel) {
    val ctx = LocalContext.current
    var locked by remember { mutableStateOf(AppLock.needsUnlock(vm.lockMode)) }
    var lockNote by remember { mutableStateOf("") }
    val tryUnlock = {
        val act = ctx as? FragmentActivity
        if (act != null) AppLock.prompt(act, vm.lockMode, { locked = false; lockNote = "" }, { lockNote = it })
    }
    if (locked) {
        LaunchedEffect(Unit) {
            if (!AppLock.available(ctx, vm.lockMode)) lockNote = "This phone has no screen lock or fingerprint set up for that choice. Change it in Settings > Watchtower."
            else tryUnlock()
        }
        Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            Text("Watchtower is locked", fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Text(if (lockNote.isEmpty()) "Unlock to see your cameras." else lockNote, color = Ow.Muted, textAlign = TextAlign.Center, modifier = Modifier.padding(vertical = 12.dp))
            Button(onClick = { tryUnlock() }, shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Unlock") }
        }
        return
    }
    LaunchedEffect(Unit) { while (true) { AppLock.touch(); delay(5000) } }
    LaunchedEffect(Unit) { if (vm.linkedCams.isNotEmpty() || vm.hasWg()) vm.connectHome(ctx) }
    Viewer(vm)
}

@Composable
private fun Viewer(vm: OverwatchViewModel) {
    val cams = vm.viewCams()
    var drawer by remember { mutableStateOf(false) }
    var sound by remember { mutableStateOf(false) }
    var pendingDock by remember { mutableStateOf<ViewCam?>(null) }
    var note by remember { mutableStateOf("") }
    val ctls = remember { HashMap<String, TileCtl>() }
    fun ctl(id: String) = ctls.getOrPut(id) { TileCtl() }
    val slots = vm.fixedSlots()
    val one = cams.firstOrNull { it.id == vm.wtOne } ?: cams.firstOrNull()
    val shown = if (vm.wtMode == 1) listOfNotNull(one) else slots.mapNotNull { id -> cams.firstOrNull { it.id == id } }
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { drawer = true }) { Text("☰", fontSize = 24.sp, color = Ow.Bone) }
                Text(if (vm.wtMode == 1) (one?.name ?: "No cameras") else "4 cameras", fontWeight = FontWeight.Bold, fontSize = 17.sp, modifier = Modifier.weight(1f))
                Text(if (vm.linkHost != null) "Home link on" else "", fontSize = 11.sp, color = Ow.Green)
            }
            if (cams.isEmpty()) {
                Text("No cameras yet. Add one in Settings > Watchtower, or paste your PC's pairing code there to bring over its cameras.", color = Ow.Muted, fontSize = 13.sp)
            } else if (vm.wtMode == 1 && one != null) {
                CameraTile(vm, one, sub = false, sound = sound, ctl = ctl(one.id), modifier = Modifier.fillMaxWidth().aspectRatio(16f / 10f)) {}
            } else {
                for (row in shown.chunked(2)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        row.forEach { vc ->
                            CameraTile(vm, vc, sub = true, sound = false, ctl = ctl(vc.id), modifier = Modifier.weight(1f).aspectRatio(4f / 3f)) {
                                vm.chooseOne(vc.id); vm.chooseMode(1)
                            }
                        }
                        if (row.size == 1) Box(Modifier.weight(1f))
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val players = shown.mapNotNull { ctl(it.id).player }
                val recording = players.any { it.recording }
                ControlButton(if (recording) "Stop" else "Record", Modifier.weight(1f), if (recording) Ow.Red else Ow.Panel) {
                    if (recording) {
                        val where = players.mapNotNull { it.stopRecord() }.firstOrNull()
                        note = if (where != null) "Saved to $where" else "Could not save the recording."
                    } else {
                        val ok = players.count { it.startRecord() }
                        note = if (ok > 0) "Recording..." else "Wait for the picture to show, then record."
                    }
                }
                ControlButton(if (vm.wtMode == 1) "Show 4" else "Show 1", Modifier.weight(1f)) { vm.chooseMode(if (vm.wtMode == 1) 4 else 1) }
                ControlButton(if (sound) "Sound on" else "Sound off", Modifier.weight(1f)) { sound = !sound }
            }
            if (note.isNotEmpty()) Text(note, fontSize = 12.sp, color = Ow.Muted)
            if (vm.linkNote.isNotEmpty()) Text(vm.linkNote, fontSize = 12.sp, color = Ow.Muted)
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("ALERTS", fontSize = 12.sp, color = Ow.Blue, fontWeight = FontWeight.Bold)
                if (vm.alerts.isEmpty()) Text("No alerts yet. Alerts for people and vehicles show here.", fontSize = 12.sp, color = Ow.Muted)
                vm.alerts.forEach { (whenText, text) -> Row { Text(whenText, fontSize = 12.sp, color = Ow.Muted, modifier = Modifier.width(72.dp)); Text(text, fontSize = 12.sp) } }
            }
        }
        if (drawer) {
            Box(Modifier.fillMaxSize().background(Color(0x99080A0C)).clickable { drawer = false })
            Column(Modifier.fillMaxHeight().fillMaxWidth(0.78f).background(Ow.Panel).verticalScroll(rememberScrollState()).padding(10.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("CAMERAS", fontSize = 12.sp, color = Ow.Muted, modifier = Modifier.padding(6.dp))
                if (cams.isEmpty()) Text("No cameras yet.", color = Ow.Muted, modifier = Modifier.padding(6.dp))
                cams.forEach { vc ->
                    val dock = slots.indexOf(vc.id)
                    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(if ((vm.wtMode == 1 && vc.id == one?.id) || (vm.wtMode == 4 && dock >= 0)) Ow.PanelHigh else Ow.Panel)
                        .clickable {
                            drawer = false
                            if (vm.wtMode == 1) vm.chooseOne(vc.id) else pendingDock = vc
                        }.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(vc.name, fontWeight = FontWeight.SemiBold)
                            Text(if (vc.linked != null) "From your home PC" else "Added on this phone", fontSize = 11.sp, color = Ow.Muted)
                        }
                        if (vm.wtMode == 4 && dock >= 0) Text("${dock + 1}", color = Ow.Blue, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
    pendingDock?.let { vc ->
        AlertDialog(
            onDismissRequest = { pendingDock = null },
            containerColor = Ow.Panel,
            title = { Text("Select the dock for ${vc.name}") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Tap the number where you want this feed. It replaces the camera that is there now.", fontSize = 13.sp, color = Ow.Muted)
                    for (r in 0..1) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for (c in 0..1) {
                            val i = r * 2 + c
                            val there = cams.firstOrNull { it.id == slots[i] }?.name ?: "empty"
                            Column(Modifier.weight(1f).clip(RoundedCornerShape(10.dp)).background(Ow.Charcoal).clickable { vm.placeInDock(vc.id, i); pendingDock = null }.padding(12.dp),
                                horizontalAlignment = Alignment.CenterHorizontally) {
                                Text("${i + 1}", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Ow.Blue)
                                Text(there, fontSize = 11.sp, color = Ow.Muted, maxLines = 1)
                            }
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { pendingDock = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun ControlButton(text: String, modifier: Modifier, color: Color = Ow.Panel, onClick: () -> Unit) {
    Button(onClick = onClick, modifier = modifier.height(48.dp), shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(containerColor = color, contentColor = Ow.Bone)) { Text(text, fontSize = 13.sp, maxLines = 1) }
}

@Composable
fun CameraTile(vm: OverwatchViewModel, vc: ViewCam, sub: Boolean, sound: Boolean, ctl: TileCtl, modifier: Modifier, onClick: () -> Unit) {
    val ctx = LocalContext.current
    val address = vm.address(vc, sub)
    val player = remember(vc.id, address) { CamPlayer(ctx, vc.name) }
    DisposableEffect(player) {
        ctl.player = player
        onDispose { player.release(); if (ctl.player === player) ctl.player = null }
    }
    LaunchedEffect(player) { if (address != null) player.play(address, sound) }
    LaunchedEffect(sound) { player.setSound(sound) }
    Box(modifier.clip(RoundedCornerShape(10.dp)).background(Color.Black).clickable { onClick() }) {
        if (address != null) {
            AndroidView(
                factory = { c -> VLCVideoLayout(c).also { player.player.attachViews(it, null, false, false) } },
                onRelease = { player.player.detachViews() },
                modifier = Modifier.fillMaxSize(),
            )
        }
        if (address == null || player.state == "offline") OfflineScreen(if (address == null) "Cannot reach your home PC..." else "Camera is offline...")
        Row(Modifier.padding(8.dp).clip(RoundedCornerShape(99.dp)).background(Color(0xCC0F1113)).padding(horizontal = 8.dp, vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(if (player.recording || address == null || player.state == "offline") Ow.Red else Ow.Green))
            Text(" " + vc.name + if (player.recording) "  REC" else "", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

/** The black screen with a crossed-out eye shown when a camera cannot be reached. */
@Composable
fun OfflineScreen(text: String) {
    Column(Modifier.fillMaxSize().background(Color.Black), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        val c = Color(0xFFA9B0B6)
        Canvas(Modifier.size(44.dp)) {
            val w = size.width
            val h = size.height
            drawOval(c, topLeft = Offset(0f, h * 0.2f), size = Size(w, h * 0.6f), style = Stroke(width = 3f))
            drawCircle(c, radius = w * 0.14f, center = Offset(w / 2, h / 2), style = Stroke(width = 3f))
            drawLine(c, Offset(w * 0.08f, h * 0.08f), Offset(w * 0.92f, h * 0.92f), strokeWidth = 4f)
        }
        Text(text, color = c, fontSize = 13.sp, modifier = Modifier.padding(top = 8.dp), textAlign = TextAlign.Center)
    }
}
