package com.cindrix.overwatch

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

object Ow {
    val Charcoal = Color(0xFF1F2226)
    val Panel = Color(0xFF2A2E33)
    val PanelHigh = Color(0xFF363B41)
    val MapBg = Color(0xFF171A1D)
    val Land = Color(0xFF2F353B)
    val Bone = Color(0xFFECE6D8)
    val Muted = Color(0xFF9AA3AB)
    val Blue = Color(0xFF67B4FF)
    val BlueDeep = Color(0xFF3B9BFF)
    val OnBlue = Color(0xFF07101F)
    val Outline = Color(0xFF4A5159)
    val Green = Color(0xFF4CB782)
    val Amber = Color(0xFFE0A33A)
    val Orange = Color(0xFFF08A3C)
    val Red = Color(0xFFE5534B)
    val Levels = listOf(Green, Amber, Orange, Red)

    fun kindColor(k: Kind): Color = when (k) {
        Kind.MILITARY -> Blue
        Kind.CONFLICT -> Red
        Kind.HAZARD, Kind.WEATHER, Kind.SPACE -> Amber
        Kind.HEALTH -> Orange
        Kind.NEWS, Kind.CYBER -> Muted
    }
}

/** The app is always dark: it is a war-room screen, and dark saves battery on the Note10 hub. */
@Composable
fun OverwatchTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Ow.Blue, onPrimary = Ow.OnBlue, secondary = Ow.BlueDeep, background = Ow.Charcoal, onBackground = Ow.Bone,
            surface = Ow.Panel, onSurface = Ow.Bone, surfaceVariant = Ow.PanelHigh, onSurfaceVariant = Ow.Muted,
            outline = Ow.Outline, error = Ow.Red,
        ),
        content = content,
    )
}
