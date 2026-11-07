package com.cindrix.overwatch

import com.google.android.gms.tasks.Tasks
import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.nl.languageid.LanguageIdentification
import com.google.mlkit.nl.translate.TranslateLanguage
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions

/**
 * Translating foreign headlines into English with Google ML Kit. The language is found on the phone, each language pack is
 * downloaded from Google once (then it works offline), and the translating itself happens on the phone. Only public
 * headlines are translated. Blocks while it works, so call it off the main thread.
 */
object MlTranslate {
    /**
     * One entry per text: the English text, "" when the text is not worth translating (already English, or a language Google
     * does not offer), or null when it could not be done now (for example no internet to fetch the language pack), so it is tried again later.
     */
    fun translate(texts: List<String>): List<String?> {
        val ident = LanguageIdentification.getClient()
        val translators = HashMap<String, Translator>()
        try {
            return texts.map { text ->
                try {
                    val code = Tasks.await(ident.identifyLanguage(text))
                    if (code == "und" || code == "en") return@map ""
                    val lang = TranslateLanguage.fromLanguageTag(code) ?: return@map ""
                    val tr = translators.getOrPut(lang) {
                        Translation.getClient(TranslatorOptions.Builder().setSourceLanguage(lang).setTargetLanguage(TranslateLanguage.ENGLISH).build())
                    }
                    Tasks.await(tr.downloadModelIfNeeded(DownloadConditions.Builder().build()))
                    Tasks.await(tr.translate(text))
                } catch (e: Exception) {
                    null
                }
            }
        } finally {
            translators.values.forEach { it.close() }
            ident.close()
        }
    }
}
