package com.cindrix.overwatch

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog

private val TIER_FILTERS = listOf(null to "All", "works" to "Works", "enable" to "Turn it on first", "some" to "Some models", "no" to "Not supported")

private fun tierColor(tier: String) = when (tier) { "works" -> Ow.Green; "enable" -> Ow.Blue; "some" -> Ow.Amber; else -> Ow.Red }

/** Settings > Watchtower: the camera list (any number, each with a switch), adding a camera, and the small "Which cameras work?" window. */
@Composable
fun WatchtowerSection(vm: OverwatchViewModel) {
    var name by remember { mutableStateOf("") }
    var brandId by remember { mutableStateOf("other") }
    var host by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("") }
    var user by remember { mutableStateOf("") }
    var pass by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var noteBad by remember { mutableStateOf(false) }
    var showSupported by remember { mutableStateOf(false) }
    val cat = vm.engine.cameraCatalog
    val choices = cat.brands.filter { it.tier != "no" }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Watchtower: your cameras", fontWeight = FontWeight.Bold, fontSize = 18.sp, modifier = Modifier.weight(1f))
            TextButton(onClick = { showSupported = true }) { Text("Which cameras work?", fontSize = 12.sp, color = Ow.Muted) }
        }
        Text("Add a camera. Any number. Each one gets its own on/off switch below.", fontSize = 12.sp, color = Ow.Muted)
        OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Name") })
        Text("Make", fontSize = 12.sp, color = Ow.Muted)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(choices) { b -> FilterChip(selected = brandId == b.id, onClick = { brandId = b.id }, label = { Text(b.name) }) }
        }
        val hint = cat.brand(brandId)?.let { it.setup.ifEmpty { it.note } } ?: ""
        if (hint.isNotEmpty()) Text(hint, fontSize = 12.sp, color = Ow.Muted)
        OutlinedTextField(host, { host = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Address (IP, or the whole rtsp:// address)") })
        OutlinedTextField(port, { port = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Port (if not usual)") })
        OutlinedTextField(user, { user = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Username") })
        OutlinedTextField(pass, { pass = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Password") }, visualTransformation = PasswordVisualTransformation())
        Button(onClick = {
            val err = vm.addCamera(name, brandId, host, user, pass, port)
            noteBad = err != null
            note = err ?: "Added. It is in the list below with its own switch."
            if (err == null) { name = ""; host = ""; port = ""; user = ""; pass = "" }
        }, shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Add camera") }
        if (note.isNotEmpty()) Text(note, fontSize = 12.sp, color = if (noteBad) Ow.Red else Ow.Muted)
        if (vm.cameras.isEmpty()) Text("No cameras yet. Add one above. Not sure what works? Open \"Which cameras work?\" at the top.", fontSize = 12.sp, color = Ow.Muted)
        vm.cameras.forEach { cam ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Ow.PanelHigh).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(cam.name, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = if (cam.enabled) Ow.Bone else Ow.Muted)
                    Text((cat.brand(cam.brand)?.name ?: "Camera") + "  ·  " + Cameras.shownAddress(cam) + if (cam.user.isNotEmpty()) "  ·  login saved" else "",
                        fontSize = 11.sp, color = Ow.Muted)
                }
                TextButton(onClick = { vm.removeCamera(cam.id) }) { Text("Remove") }
                Switch(checked = cam.enabled, onCheckedChange = { vm.setCameraEnabled(cam.id, it) })
            }
        }
    }
    if (showSupported) SupportedCamerasDialog(cat) { showSupported = false }
}

/** The pop-up listing every make Watchtower can show, with the address style each one uses. */
@Composable
fun SupportedCamerasDialog(cat: Catalog, onClose: () -> Unit) {
    var tier by remember { mutableStateOf<String?>(null) }
    var q by remember { mutableStateOf("") }
    val shown = cat.brands.filter { b ->
        (tier == null || b.tier == tier) && (q.isBlank() || (b.name + " " + b.models).contains(q.trim(), ignoreCase = true))
    }
    Dialog(onDismissRequest = onClose) {
        Column(Modifier.clip(RoundedCornerShape(16.dp)).background(Ow.Charcoal).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Cameras Watchtower can show", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text(cat.about, fontSize = 12.sp, color = Ow.Muted)
            LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(TIER_FILTERS) { (k, label) -> FilterChip(selected = tier == k, onClick = { tier = k }, label = { Text(label) }) }
            }
            OutlinedTextField(q, { q = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Search") })
            LazyColumn(Modifier.heightIn(max = 420.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                items(shown) { b ->
                    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Ow.Panel).padding(12.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(b.name, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                            Text("   " + (cat.tiers[b.tier] ?: ""), fontSize = 11.sp, color = tierColor(b.tier))
                        }
                        Text(b.models, fontSize = 12.sp)
                        if (b.main.isNotEmpty()) {
                            val ex = Cameras.buildAddress(cat, b.id, "CAMERA-IP", null, "main")
                            val sub = if (b.sub.isNotEmpty()) "\nSub-stream:  " + Cameras.buildAddress(cat, b.id, "CAMERA-IP", null, "sub") else ""
                            Text("Address style:  $ex$sub", fontSize = 11.sp, color = Ow.Muted)
                        }
                        if (b.setup.isNotEmpty()) Text("Setup:  " + b.setup, fontSize = 11.sp, color = Ow.Muted)
                        Text(b.note, fontSize = 11.sp, color = Ow.Muted)
                    }
                }
                if (shown.isEmpty()) item { Text("Nothing matches. Try another word or filter.", fontSize = 12.sp, color = Ow.Muted, modifier = Modifier.padding(8.dp)) }
            }
            TextButton(onClick = onClose, modifier = Modifier.align(Alignment.End)) { Text("Close") }
        }
    }
}
