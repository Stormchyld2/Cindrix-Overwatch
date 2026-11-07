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
                1 -> IntelScreen(vm)
                2 -> FeedScreen(vm)
                3 -> BriefScreen(vm)
                4 -> WatchtowerScreen(vm)
                else -> SettingsScreen(vm)
            }
        }
        NavigationBar(containerColor = Ow.Panel) {
            listOf("Map", "Intel", "Feed", "Brief", "Watchtower", "Settings").forEachIndexed { i, label ->
                NavigationBarItem(selected = vm.tab == i, onClick = { vm.tab = i }, icon = {}, label = { Text(label, fontSize = 12.sp, maxLines = 1) },
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
        Image(painterResource(R.drawable.header_icon), contentDescription = "Cindrix Overwatch", modifier = Modifier.size(44.dp).clip(RoundedCornerShape(10.dp)))
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
            items(listOf(Kind.MILITARY to "Military", Kind.CONFLICT to "Conflict", Kind.HAZARD to "Hazards", Kind.WEATHER to "Weather", Kind.NEWS to "News")) { (k, label) ->
                FilterChip(selected = k in vm.layers, onClick = { vm.toggleLayer(k) }, label = { Text(label) })
            }
            item { FilterChip(selected = vm.deployOn, onClick = { vm.deployOn = !vm.deployOn }, label = { Text("Troop movements") }) }
            item { FilterChip(selected = vm.mineOn, onClick = { vm.mineOn = !vm.mineOn }, label = { Text("My pins") }) }
        }
        vm.pinTarget?.let { t ->
            Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp).clip(RoundedCornerShape(10.dp)).background(Ow.Blue).padding(horizontal = 12.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("Tap the map to place: " + t.shown.take(70), fontSize = 12.sp, color = Ow.OnBlue, modifier = Modifier.weight(1f), maxLines = 2)
                TextButton(onClick = { vm.cancelPin() }) { Text("Cancel", color = Ow.OnBlue) }
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
            Text(it.shown, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, maxLines = 3)
            val more = if (it.count > 1) "  ·  ${it.count} sources" else ""
            val place = if (it.place.isNotEmpty()) "  ·  ${it.place}" else ""
            Text("${it.source}  ·  ${it.trust.label}$more$place  ·  ${ago(it.ts, nowSeconds())}", fontSize = 11.sp, color = Ow.Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                if (it.url.isNotEmpty()) TextButton(onClick = { vm.openReader(it) }) { Text("Read here") }
                if (it.url.isNotEmpty()) TextButton(onClick = { openUrl(ctx, it.url) }) { Text("Open page") }
                TextButton(onClick = { vm.startPin(it) }) { Text(if (it.mine) "Move pin" else if (it.pinned) "Re-pin" else "Pin it") }
                if (it.mine) TextButton(onClick = { vm.removePin(it) }) { Text("Remove pin") }
            }
            if (vm.pinNote.isNotEmpty()) Text(vm.pinNote, fontSize = 11.sp, color = Ow.Muted)
        }
    }
}

@Composable
fun IntelScreen(vm: OverwatchViewModel) {
    val reading = vm.reader
    if (reading != null) { ReaderView(vm, reading); return }
    if (vm.intelDash) { DashboardScreen(vm); return }
    val ctx = LocalContext.current
    val list = vm.intelList()
    Column(Modifier.fillMaxSize()) {
        LazyRow(Modifier.padding(top = 8.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            item { FilterChip(selected = false, onClick = { vm.intelDash = true }, label = { Text("← Dashboard") }) }
            items(INTEL_CHANNELS) { c ->
                FilterChip(selected = vm.channel == c.id, onClick = { vm.channel = c.id }, label = { Text("${c.label} (${vm.channelCount(c.id)})") })
            }
            item { FilterChip(selected = vm.troopsOnly, onClick = { vm.troopsOnly = !vm.troopsOnly }, label = { Text("Troop movements only") }) }
        }
        Box(Modifier.padding(horizontal = 8.dp, vertical = 4.dp)) { IntelFilters(vm) }
        OutlinedTextField(vm.intelSearch, { vm.intelSearch = it }, Modifier.fillMaxWidth().padding(8.dp), singleLine = true, placeholder = { Text("Search this channel") })
        if (list.isEmpty()) {
            Text(if (vm.items.isEmpty()) "Nothing here yet. Tap Refresh while online. Saved items show even offline." else "Nothing in this channel right now.",
                color = Ow.Muted, modifier = Modifier.padding(16.dp))
        }
        LazyColumn(Modifier.weight(1f), contentPadding = androidx.compose.foundation.layout.PaddingValues(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(list, key = { it.uid }) { item -> IntelCard(vm, item) { openUrl(ctx, item.url) } }
        }
    }
}

@Composable
fun IntelFilters(vm: OverwatchViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text("Where", fontSize = 11.sp, color = Ow.Muted, modifier = Modifier.padding(start = 4.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(REGION_CHOICES) { (label, _) -> FilterChip(selected = vm.regionLabel == label, onClick = { vm.setRegion(label) }, label = { Text(label) }) }
        }
        Text("How serious", fontSize = 11.sp, color = Ow.Muted, modifier = Modifier.padding(start = 4.dp, top = 4.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(SEVERITY_CHOICES) { (label, n) -> FilterChip(selected = vm.minSev == n, onClick = { vm.setSeverity(n) }, label = { Text(label) }) }
        }
        if (vm.regionCode() != null) Text("A region needs a map pin, so stories not on the map are hidden while one is chosen.", fontSize = 11.sp, color = Ow.Muted,
            modifier = Modifier.padding(start = 4.dp, top = 2.dp))
    }
}

@Composable
fun DashboardScreen(vm: OverwatchViewModel) {
    val pad = androidx.compose.foundation.layout.PaddingValues(10.dp)
    LazyColumn(Modifier.fillMaxSize(), contentPadding = pad, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { IntelFilters(vm) }
        item {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) { items(vm.indicators) { IndicatorTile(it) } }
        }
        item {
            DashPanel("TOP 10 FOR EARLY WARNING", Ow.Blue, "", null) {
                if (vm.top.isEmpty()) Text("Nothing here yet. Tap Refresh while online.", fontSize = 12.sp, color = Ow.Muted)
                vm.top.forEachIndexed { k, (item, why) -> DashRow(vm, item, rank = k + 1, reasons = why) }
            }
        }
        item {
            val rows = vm.troopRows()
            DashPanel("TROOP MOVEMENTS", Ow.Amber, "${rows.size} in 24 h", { vm.seeAll("military", troops = true) }) {
                if (rows.isEmpty()) Text("No deployment signals in the last 24 hours.", fontSize = 12.sp, color = Ow.Muted)
                rows.forEach { DashRow(vm, it) }
            }
        }
        for (c in INTEL_CHANNELS) {
            item(key = "panel-" + c.id) {
                val rows = vm.dashRows(c.id)
                DashPanel(c.label.uppercase(), Ow.kindColor(c.kinds.first()), vm.channelCount(c.id).toString(), { vm.seeAll(c.id) }) {
                    if (rows.isEmpty()) Text("Nothing here yet.", fontSize = 12.sp, color = Ow.Muted)
                    rows.forEach { DashRow(vm, it) }
                }
            }
        }
    }
}

@Composable
fun DashPanel(title: String, color: Color, count: String, onSeeAll: (() -> Unit)?, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Ow.Panel).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(Modifier.size(10.dp).clip(RoundedCornerShape(5.dp)).background(color))
            Text(title, fontWeight = FontWeight.Bold, fontSize = 14.sp, letterSpacing = 1.sp, modifier = Modifier.weight(1f))
            if (count.isNotEmpty()) Text(count, fontSize = 11.sp, color = Ow.Muted)
            if (onSeeAll != null) TextButton(onClick = onSeeAll, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)) { Text("See all →", fontSize = 12.sp) }
        }
        content()
    }
}

@Composable
fun DashRow(vm: OverwatchViewModel, item: Item, rank: Int? = null, reasons: List<String> = emptyList()) {
    val col = Ow.kindColor(item.kind)
    val tags = (reasons.ifEmpty { if (isDeployment(item)) listOf("troop movement") else emptyList() } + if (!item.pinned) listOf("not on map") else emptyList()).take(3)
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(if (rank != null) Ow.PanelHigh else Ow.Panel).clickable { vm.openReader(item) }
        .padding(horizontal = 8.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
        if (rank != null) Text(rank.toString(), fontWeight = FontWeight.Bold, fontSize = 18.sp, color = col, modifier = Modifier.width(26.dp))
        Column(Modifier.weight(1f)) {
            Text(item.shown, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, maxLines = 3)
            Text("${item.source}  ·  ${ago(item.ts, nowSeconds())}", fontSize = 11.sp, color = Ow.Muted)
            if (tags.isNotEmpty()) Text(tags.joinToString("  ·  ") { it.uppercase() }, fontSize = 10.sp,
                color = if (tags.any { it == "troop movement" || it == "force movement" }) Ow.Amber else Ow.Blue)
        }
        if (!item.pinned && item.kind != Kind.CYBER) TextButton(onClick = { vm.startPin(item) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)) { Text("Pin", fontSize = 12.sp) }
    }
}

@Composable
fun IntelCard(vm: OverwatchViewModel, item: Item, onOpen: () -> Unit) {
    val col = Ow.kindColor(item.kind)
    val isNew = vm.prevOpen > 0 && item.firstSeen > vm.prevOpen
    Row(Modifier.fillMaxWidth().height(androidx.compose.foundation.layout.IntrinsicSize.Min).clip(RoundedCornerShape(10.dp)).background(Ow.PanelHigh)) {
        Box(Modifier.width(4.dp).fillMaxHeight().background(col))
        Column(Modifier.padding(10.dp).weight(1f)) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(item.kind.label, fontSize = 11.sp, color = col)
                if (isNew) Text("NEW", fontSize = 11.sp, color = Ow.Blue)
                if (isHome(item, vm.home)) Text("HOME", fontSize = 11.sp, color = Ow.Blue)
                if (isDeployment(item)) Text("TROOPS", fontSize = 11.sp, color = Ow.Amber)
                if (item.mine) Text("MY PIN", fontSize = 11.sp, color = Ow.Blue)
            }
            Text(item.shown, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, modifier = Modifier.clickable { vm.openReader(item) })
            if (item.shownSummary.isNotEmpty() && item.shownSummary != item.shown) Text(item.shownSummary, fontSize = 12.sp, maxLines = 3, color = Ow.Bone)
            Text("${item.source}  ·  ${item.trust.label}" + (if (item.count > 1) ", ${item.count} sources" else "") + "  ·  ${ago(item.ts, nowSeconds())}",
                fontSize = 11.sp, color = Ow.Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = { vm.openReader(item) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)) { Text("Read", fontSize = 12.sp) }
                if (item.pinned) TextButton(onClick = { vm.select(item, centre = true) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)) { Text("Show on map", fontSize = 12.sp) }
                else TextButton(onClick = { vm.startPin(item) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)) { Text("Pin it", fontSize = 12.sp) }
                if (item.url.isNotEmpty()) TextButton(onClick = onOpen, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp)) { Text("Browser", fontSize = 12.sp) }
            }
        }
    }
}

@Composable
fun ReaderView(vm: OverwatchViewModel, item: Item) {
    val ctx = LocalContext.current
    var place by remember(item.uid) { mutableStateOf("") }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        TextButton(onClick = { vm.closeReader() }) { Text("← Back to the list") }
        Text(item.kind.label + "  ·  " + SEVERITY_WORDS[item.severity], fontSize = 11.sp, color = Ow.kindColor(item.kind))
        Text(item.shown, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        if (item.titleEn.isNotEmpty()) Text("Translated by AI. Original: " + item.title, fontSize = 11.sp, color = Ow.Muted)
        Text("${item.source}  ·  ${item.trust.label}" + (if (item.count > 1) ", ${item.count} sources" else "") + "  ·  ${ago(item.ts, nowSeconds())}" +
            (if (item.place.isNotEmpty()) "  ·  ${item.place}" else ""), fontSize = 12.sp, color = Ow.Muted)
        if (item.shownSummary.isNotEmpty() && item.shownSummary != item.shown) Text(item.shownSummary, fontSize = 14.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (item.url.isNotEmpty()) Button(onClick = { vm.readArticle() }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Read the article here") }
            if (item.url.isNotEmpty()) Button(onClick = { openUrl(ctx, item.url) }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Open in browser") }
        }
        if (vm.readerNote.isNotEmpty()) Text(vm.readerNote, fontSize = 12.sp, color = Ow.Muted)
        if (vm.readerText.isNotEmpty()) {
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp)) { Text(vm.readerText, fontSize = 14.sp) }
        }
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("Map pin", fontWeight = FontWeight.SemiBold)
            Text(if (item.pinned) "Pinned: ${item.place}" else "Not on the map.", fontSize = 12.sp, color = Ow.Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (item.pinned) Button(onClick = { vm.select(item, centre = true) }, shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Show on map") }
                Button(onClick = { vm.startPin(item) }, shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text(if (item.pinned) "Move pin (tap map)" else "Pin it (tap map)") }
            }
            OutlinedTextField(place, { place = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Or type a place, like Taipei or Black Sea") })
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { vm.pinByName(item, place) }, enabled = place.isNotBlank(), shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Pin to that place") }
                if (item.mine) Button(onClick = { vm.removePin(item) }, shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Remove my pin") }
            }
            if (vm.pinNote.isNotEmpty()) Text(vm.pinNote, fontSize = 12.sp, color = Ow.Muted)
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
            Text(item.shown, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            if (item.titleEn.isNotEmpty()) Text("Translated by AI. Original: " + item.title, fontSize = 11.sp, color = Ow.Muted)
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

/** The kind a new feed files under for each of the four Intel categories. */
private val FEED_CATEGORIES = listOf("military" to "Military", "news" to "World news", "cyber" to "Cyber", "hazard" to "Alerts and weather")

@Composable
fun FeedsSection(vm: OverwatchViewModel) {
    var name by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("") }
    var kind by remember { mutableStateOf("news") }
    var note by remember { mutableStateOf("") }
    val now = nowSeconds()
    val ctx = androidx.compose.ui.platform.LocalContext.current
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Feeds", fontWeight = FontWeight.Bold, fontSize = 18.sp)
        Text("Every feed Overwatch reads, each with its own switch. Add your own below and it appears in this list with a switch too.", fontSize = 12.sp, color = Ow.Muted)
        Text("Add your own feed (RSS or Atom, https only)", fontWeight = FontWeight.SemiBold)
        OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Name") })
        OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Address") })
        Text("Category (where it shows on the Intel dashboard)", fontSize = 12.sp, color = Ow.Muted)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(FEED_CATEGORIES) { (k, label) -> FilterChip(selected = kind == k, onClick = { kind = k }, label = { Text(label) }) }
        }
        Button(onClick = {
            val err = vm.addFeed(name, url, kind)
            note = err ?: "Added. It is in the list below and will be checked now."
            if (err == null) { name = ""; url = "" }
        }, shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Add feed") }
        if (note.isNotEmpty()) Text(note, fontSize = 12.sp, color = Ow.Muted)
        Button(onClick = { shareSourceList(ctx, vm.sources) }, shape = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Share source list (CSV)") }
        vm.sources.groupBy { it.src.group }.forEach { (group, rows) ->
            Text(group.uppercase(), fontSize = 11.sp, color = Ow.Muted, modifier = Modifier.padding(top = 8.dp))
            rows.forEach { row ->
                val h = row.health
                val status = when {
                    !row.enabled -> "turned off"
                    h == null -> "not checked yet"
                    h.ok -> "working, ${h.count} items, " + ago(h.lastOk ?: 0.0, now)
                    else -> "problem: " + h.error.ifEmpty { "failed" }
                }
                val cat = INTEL_CHANNELS.firstOrNull { row.src.kind in it.kinds }?.label ?: ""
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Ow.PanelHigh).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(row.src.name, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = if (row.enabled) Ow.Bone else Ow.Muted)
                        Text("$cat  ·  ${row.src.trust.label}", fontSize = 11.sp, color = Ow.Muted)
                        Text(status, fontSize = 11.sp, color = if (h != null && !h.ok && row.enabled) Ow.Red else Ow.Muted)
                    }
                    if (row.custom >= 0) TextButton(onClick = { vm.removeFeed(row.custom) }) { Text("Remove") }
                    Switch(checked = row.enabled, onCheckedChange = { vm.setEnabled(row.src.id, it) })
                }
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
        FeedsSection(vm)
        WatchtowerSection(vm)
        PhoneLinkSection(vm)
        LockSection(vm)
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
            Text("Onion feeds you add in Sources are read through Tor already running on this phone (Orbot).", fontSize = 12.sp, color = Ow.Muted)
            Button(onClick = { vm.checkTor() }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Check for Tor on this phone") }
            if (vm.torNote.isNotEmpty()) Text(vm.torNote, fontSize = 12.sp, color = Ow.Muted)
        }
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Translate foreign headlines", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text("Uses Google ML Kit. The phone works out the language and translates on the phone. Each language pack (about 30 MB) is " +
                "downloaded from Google once, then works offline. Only public headlines are translated, and the original stays under the English.", fontSize = 12.sp, color = Ow.Muted)
            Button(onClick = { vm.toggleTranslate() }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = if (vm.translateOn) Ow.Blue else Ow.PanelHigh, contentColor = if (vm.translateOn) Ow.OnBlue else Ow.Bone)) {
                Text(if (vm.translateOn) "Translation: on" else "Translation: off")
            }
        }
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Ow.Panel).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            var aiText by remember { mutableStateOf(vm.aiUrl) }
            Text("AI helper (optional)", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Text("A phone cannot run the model. Type the address of a computer on your network that runs one (for example http://192.168.1.20:8080). " +
                "With it set, Overwatch can place stories on the map. The brief and the translation never use it. Leave empty to keep the AI off.", fontSize = 12.sp, color = Ow.Muted)
            OutlinedTextField(aiText, { aiText = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("AI server address") })
            Button(onClick = { aiText = "http://127.0.0.1:8089" }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Ow.PanelHigh, contentColor = Ow.Bone)) { Text("Use the Cindrix Hub on this phone") }
            Text("That fills in the address the Hub's model will use once the Hub is built (port 8089). Until then, leave the AI off.", fontSize = 11.sp, color = Ow.Muted)
            Button(onClick = { vm.saveAiUrl(aiText) }, shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Ow.Blue, contentColor = Ow.OnBlue)) { Text("Save") }
            if (vm.aiNote.isNotEmpty()) Text(vm.aiNote, fontSize = 12.sp, color = Ow.Muted)
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
