package com.cindrix.overwatch

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

fun ago(ts: Double, now: Double): String {
    if (ts <= 0) return "never"
    val s = maxOf(0, (now - ts).toLong())
    return when {
        s < 90 -> "just now"
        s < 3600 -> "${s / 60} min ago"
        s < 86400 -> "${s / 3600} h ago"
        else -> "${s / 86400} d ago"
    }
}

fun openUrl(ctx: android.content.Context, url: String) {
    if (url.lowercase().startsWith("https://") || url.lowercase().startsWith("http://")) {
        try { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } catch (_: Exception) {}
    }
}

@Composable
fun OverwatchApp(vm: OverwatchViewModel) {
    val cam = remember { MapCamera() }
    Column(Modifier.fillMaxSize().background(Ow.Charcoal).windowInsetsPadding(WindowInsets.systemBars)) {
        TopBar(vm)
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (vm.tab) {
                0 -> MapScreen(vm, cam)
                1 -> FeedScreen(vm)
                2 -> BriefScreen(vm)
                3 -> SourcesScreen(vm)
                else -> SettingsScreen(vm)
            }
        }
        NavigationBar(containerColor = Ow.Panel) {
            listOf("Map", "Feed", "Brief", "Sources", "Settings").forEachIndexed { i, label ->
                NavigationBarItem(selected = vm.tab == i, onClick = { vm.tab = i }, icon = {}, label = { Text(label, fontSize = 13.sp) },
                    alwaysShowLabel = true)
            }
        }
    }
}

@Composable
fun TopBar(vm: OverwatchViewModel) {
    val now = nowSeconds()
    val offline = vm.lastRefresh > 0 && vm.sources.isNotEmpty() && vm.sources.none { it.health?.ok == true }
    Row(Modifier.fillMaxWidth().background(Ow.Panel).padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Image(painterResource(R.drawable.header_icon), contentDescription = "Cindrix Overwatch", modifier = Modifier.size(34.dp).clip(RoundedCornerShape(8.dp)))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text("CINDRIX OVERWATCH", fontWeight = FontWeight.Bold, fontSize = 16.sp, letterSpacing = 1.sp)
            Text(
                when {
                    vm.refreshing -> vm.progress.ifEmpty { "Refreshing..." }
                    vm.lastRefresh <= 0 -> "No data yet. Tap Refresh."
                    offline -> "Offline: showing saved data from " + ago(vm.lastRefresh, now)
                    else -> "Updated " + ago(vm.lastRefresh, now)
                },
                fontSize = 11.sp, color = if (offline) Ow.Amber else Ow.Muted,
            )
        }
        Button(onClick = { vm.refresh(true) }, enabled = !vm.refreshing, shape = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Refresh") }
    }
}

@Composable
fun IndicatorTile(ind: Indicator) {
    val col = Ow.Levels[ind.level]
    Column(Modifier.width(138.dp).clip(RoundedCornerShape(10.dp)).background(Ow.Panel)) {
        Box(Modifier.fillMaxWidth().height(3.dp).background(col))
        Column(Modifier.padding(horizontal = 10.dp, vertical = 6.dp)) {
            Text(ind.label.uppercase(), fontSize = 10.sp, color = Ow.Muted, maxLines = 1)
            Text(ind.word, fontSize = 18.sp, fontWeight = FontWeight.Bold, color = col, maxLines = 1)
            Text(ind.note, fontSize = 10.sp, color = Ow.Muted, maxLines = 2)
        }
    }
}

@Composable
fun MapScreen(vm: OverwatchViewModel, cam: MapCamera) {
    Column(Modifier.fillMaxSize()) {
        LazyRow(Modifier.padding(vertical = 8.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(vm.indicators) { IndicatorTile(it) }
        }
        LazyRow(contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(listOf(Kind.MILITARY to "Military", Kind.CONFLICT to "Conflict", Kind.HAZARD to "Hazards", Kind.NEWS to "News")) { (k, label) ->
                FilterChip(selected = k in vm.layers, onClick = { vm.toggleLayer(k) }, label = { Text(label) })
            }
        }
        Box(Modifier.weight(1f).fillMaxWidth().padding(8.dp).clip(RoundedCornerShape(12.dp))) {
            WorldMap(vm, cam)
            Column(Modifier.align(Alignment.TopEnd).padding(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                MapButton("+") { cam.zoomAt(cam.w / 2, cam.h / 2, 1.5f) }
                MapButton("−") { cam.zoomAt(cam.w / 2, cam.h / 2, 0.67f) }
                MapButton("⌂") { vm.homePoint?.let { cam.centerOn(it.first, it.second) } }
                MapButton("↺") { cam.reset() }
            }
        }
        SelectedCard(vm)
    }
}

@Composable
fun MapButton(text: String, onClick: () -> Unit) {
    Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(Ow.Panel).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Text(text, fontSize = 18.sp, color = Ow.Bone)
    }
}

@Composable
fun SelectedCard(vm: OverwatchViewModel) {
    val ctx = LocalContext.current
    val it = vm.selected
    Column(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp).clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(12.dp)) {
        if (it == null) {
            Text("Tap a pin or a feed item to see it here", color = Ow.Muted, fontSize = 13.sp)
        } else {
            Text(it.kind.label + "  ·  " + SEVERITY_WORDS[it.severity], fontSize = 11.sp, color = Ow.kindColor(it.kind))
            Text(it.title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, maxLines = 3)
            val more = if (it.count > 1) "  ·  ${it.count} sources" else ""
            val place = if (it.place.isNotEmpty()) "  ·  ${it.place}" else ""
            Text("${it.source}  ·  ${it.trust.label}$more$place  ·  ${ago(it.ts, nowSeconds())}", fontSize = 11.sp, color = Ow.Muted)
            if (it.url.isNotEmpty()) TextButton(onClick = { openUrl(ctx, it.url) }) { Text("Open page") }
        }
    }
}

@Composable
fun FeedScreen(vm: OverwatchViewModel) {
    val ctx = LocalContext.current
    val list = vm.visibleFeed()
    Column(Modifier.fillMaxSize()) {
        LazyRow(Modifier.padding(top = 8.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(FeedFilter.entries.toList()) { f -> FilterChip(selected = vm.filter == f, onClick = { vm.filter = f }, label = { Text(f.label) }) }
        }
        OutlinedTextField(vm.search, { vm.search = it }, Modifier.fillMaxWidth().padding(8.dp), singleLine = true, placeholder = { Text("Search the saved feed") })
        if (list.isEmpty()) {
            Text("Nothing here yet. Tap Refresh while online. Saved items show even offline.", color = Ow.Muted, modifier = Modifier.padding(16.dp))
        }
        LazyColumn(Modifier.weight(1f), contentPadding = androidx.compose.foundation.layout.PaddingValues(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(list, key = { it.uid }) { item -> FeedCard(vm, item) { openUrl(ctx, item.url) } }
        }
    }
}

@Composable
fun FeedCard(vm: OverwatchViewModel, item: Item, onOpen: () -> Unit) {
    val col = Ow.kindColor(item.kind)
    val isNew = vm.prevOpen > 0 && item.firstSeen > vm.prevOpen
    val isHomeItem = isHome(item, vm.home)
    Row(Modifier.fillMaxWidth().height(androidx.compose.foundation.layout.IntrinsicSize.Min).clip(RoundedCornerShape(10.dp)).background(Ow.PanelHigh).clickable { vm.select(item, centre = true) }) {
        Box(Modifier.width(4.dp).fillMaxHeight().background(col))
        Column(Modifier.padding(10.dp).weight(1f)) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(item.kind.label, fontSize = 11.sp, color = col)
                if (isNew) Text("NEW", fontSize = 11.sp, color = Ow.Blue)
                if (isHomeItem) Text("HOME", fontSize = 11.sp, color = Ow.Blue)
                Text("${item.source}  ·  ${ago(item.ts, nowSeconds())}", fontSize = 11.sp, color = Ow.Muted)
            }
            Text(item.title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            Text(item.trust.label + if (item.count > 1) ", ${item.count} sources" else "", fontSize = 11.sp, color = Ow.Muted)
            if (item.url.isNotEmpty()) TextButton(onClick = onOpen, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) { Text("Open page", fontSize = 12.sp) }
        }
    }
}

@Composable
fun BriefScreen(vm: OverwatchViewModel) {
    val ctx = LocalContext.current
    LaunchedEffect(vm.tab, vm.lastRefresh) { vm.loadBrief() }
    Column(Modifier.fillMaxSize().padding(12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, vm.brief)
                ctx.startActivity(Intent.createChooser(send, "Share brief").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }, shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Share brief") }
        }
        Spacer(Modifier.height(8.dp))
        Column(Modifier.weight(1f).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).verticalScroll(rememberScrollState()).padding(14.dp)) {
            Text(vm.brief, fontSize = 13.sp)
        }
    }
}

@Composable
fun SourcesScreen(vm: OverwatchViewModel) {
    var name by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    var kind by remember { mutableStateOf("news") }
    var note by remember { mutableStateOf("") }
    val now = nowSeconds()
    val ctx = androidx.compose.ui.platform.LocalContext.current
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            Button(onClick = { shareSourceList(ctx, vm.sources) }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Share source list (CSV)") }
        }
        item {
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Add your own feed (RSS or Atom, https only)", fontWeight = FontWeight.SemiBold)
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Name") })
                OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Address") })
                LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    items(listOf("news", "military", "conflict", "hazard", "health")) { k -> FilterChip(selected = kind == k, onClick = { kind = k }, label = { Text(k) }) }
                }
                Button(onClick = {
                    val err = vm.addFeed(name, url, kind)
                    note = err ?: "Added. It will be checked now."
                    if (err == null) { name = ""; url = "" }
                }, shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Add feed") }
                if (note.isNotEmpty()) Text(note, fontSize = 12.sp, color = Ow.Muted)
            }
        }
        items(vm.sources, key = { it.src.id }) { row ->
            val h = row.health
            val status = when {
                !row.enabled -> "turned off"
                h == null -> "not checked yet"
                h.ok -> "working, ${h.count} items, " + ago(h.lastOk ?: 0.0, now)
                else -> "problem: " + h.error.ifEmpty { "failed" }
            }
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Ow.Panel).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(row.src.name, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    Text("${row.src.group}  ·  ${row.src.trust.label}", fontSize = 11.sp, color = Ow.Muted)
                    Text(status, fontSize = 11.sp, color = if (h != null && !h.ok && row.enabled) Ow.Red else Ow.Muted)
                }
                if (row.custom >= 0) TextButton(onClick = { vm.removeFeed(row.custom) }) { Text("Remove") }
                else Switch(checked = row.enabled, onCheckedChange = { vm.setEnabled(row.src.id, it) })
            }
        }
    }
}

@Composable
fun SettingsScreen(vm: OverwatchViewModel) {
    var home by remember(vm.home) { mutableStateOf(vm.home.joinToString(", ")) }
    var confirm by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Home", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text("US state codes, separated by commas. Home weather, quakes near home and the home marker use these.", fontSize = 12.sp, color = Ow.Muted)
            OutlinedTextField(home, { home = it }, Modifier.fillMaxWidth(), singleLine = true)
            Button(onClick = { vm.saveHome(home) }, shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Save home") }
            if (vm.message.isNotEmpty()) Text(vm.message, fontSize = 12.sp, color = Ow.Muted)
        }
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Saved history", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text("${vm.storedCount} items kept for 30 days on this device. They show even with no internet.", fontSize = 12.sp, color = Ow.Muted)
            Button(onClick = { confirm = true }, shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Clear saved history") }
        }
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            val torCtx = androidx.compose.ui.platform.LocalContext.current
            var onion by remember { mutableStateOf("") }
            var torNote by remember { mutableStateOf("") }
            Text("Onion links (Tor)", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text("Overwatch itself never uses Tor. Paste an onion address and it opens in Tor Browser, which hides you on the Tor network.", fontSize = 12.sp, color = Ow.Muted)
            OutlinedTextField(onion, { onion = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Onion address") })
            Button(onClick = { torNote = openWithTor(torCtx, onion) ?: "" }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Open in Tor Browser") }
            if (torNote.isNotEmpty()) Text(torNote, fontSize = 12.sp, color = Ow.Muted)
        }
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("About the data", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text("Overwatch reads public feeds only: official releases, government data and news outlets. It does not log in anywhere and does not track people. " +
                "Items show who reported them. Status lights measure how much is being reported, not what is confirmed. " +
                "Pins come from places named in the headline. Version 0.1.0.", fontSize = 12.sp, color = Ow.Muted)
        }
    }
    if (confirm) AlertDialog(
        onDismissRequest = { confirm = false },
        confirmButton = { TextButton(onClick = { vm.clearHistory(); confirm = false }) { Text("Clear") } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("Cancel") } },
        title = { Text("Clear saved history") },
        text = { Text("Remove every saved item and source record from this device? Settings stay.") },
    )
}
