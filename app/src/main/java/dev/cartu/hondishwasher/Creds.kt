package dev.cartu.hondishwasher

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** The hOn account: email in plain prefs (like the widget's config.json),
 *  password in EncryptedSharedPreferences (the mobile equivalent of the keyring). */
object Creds {
    private const val FILE = "hon_secure"

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences("hon_plain", Context.MODE_PRIVATE)

    private fun secure(context: Context): SharedPreferences {
        val master = MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        return EncryptedSharedPreferences.create(
            context, FILE, master,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun email(context: Context): String = prefs(context).getString("email", "") ?: ""

    fun password(context: Context): String = secure(context).getString("password", "") ?: ""

    fun save(context: Context, email: String, password: String) {
        prefs(context).edit().putString("email", email).apply()
        secure(context).edit().putString("password", password).apply()
    }

    fun saved(context: Context): Boolean =
        email(context).contains("@") && password(context).isNotEmpty()
}
