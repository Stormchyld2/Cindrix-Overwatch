package com.cindrix.overwatch

import android.content.Context
import android.os.Build
import android.os.SystemClock
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity

enum class LockMode(val key: String, val label: String) {
    OFF("off", "Off"),
    ANY("any", "Any phone unlock (fingerprint, face, pattern or PIN)"),
    BIOMETRIC("bio", "Fingerprint or face only");

    companion object { fun of(key: String) = entries.firstOrNull { it.key == key } ?: OFF }
}

/** Locks the Watchtower tab. Android draws the unlock screen itself, so it is always in front of the app. */
object AppLock {
    private const val GRACE_MS = 60_000L
    private var unlockedAt = 0L
    private var lastSeen = 0L

    fun authenticators(mode: LockMode): Int = when (mode) {
        LockMode.ANY -> if (Build.VERSION.SDK_INT >= 30) BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL
        else BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL
        else -> BiometricManager.Authenticators.BIOMETRIC_WEAK
    }

    /** True when the phone can do this kind of unlock right now (something is set up on it). */
    fun available(ctx: Context, mode: LockMode): Boolean =
        mode == LockMode.OFF || BiometricManager.from(ctx).canAuthenticate(authenticators(mode)) == BiometricManager.BIOMETRIC_SUCCESS

    fun needsUnlock(mode: LockMode): Boolean {
        if (mode == LockMode.OFF) return false
        val now = SystemClock.elapsedRealtime()
        return unlockedAt == 0L || now - lastSeen > GRACE_MS
    }

    /** Called while Watchtower is on screen, so leaving it for a minute asks again. */
    fun touch() { lastSeen = SystemClock.elapsedRealtime() }

    fun lockNow() { unlockedAt = 0L }

    fun prompt(activity: FragmentActivity, mode: LockMode, onOk: () -> Unit, onFail: (String) -> Unit) {
        val executor = ContextCompat.getMainExecutor(activity)
        val cb = object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                unlockedAt = SystemClock.elapsedRealtime()
                touch()
                onOk()
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) { onFail(errString.toString()) }
        }
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("Unlock Watchtower")
            .setSubtitle("Your cameras are locked")
            .setAllowedAuthenticators(authenticators(mode))
            .apply { if (mode == LockMode.BIOMETRIC) setNegativeButtonText("Cancel") }
            .build()
        BiometricPrompt(activity, executor, cb).authenticate(info)
    }
}
