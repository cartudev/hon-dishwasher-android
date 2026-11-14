package dev.cartu.hondishwasher

import android.app.Application
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
        // Cache and cycle switches live in the app files dir, not ~/.config.
        Python.getInstance().getModule("mobile_api")
            .callAttr("bind_storage", filesDir.absolutePath)
    }
}

/**
 * Calls into app/src/main/python. mobile_api returns JSON text, not a dict:
 * Chaquopy types dict values as non-null PyObject, and Python None then crashes
 * with "<get-value>(...) must not be null" the moment a live inspect comes back.
 */
object PythonApi {
    private val api: PyObject by lazy {
        Python.getInstance().getModule("mobile_api")
    }

    private fun parse(result: PyObject?): Map<String, Any?> {
        val text = result?.toString()?.takeIf { it.isNotBlank() && it != "None" } ?: return emptyMap()
        return JSONObject(text).toKotlinMap()
    }

    private fun JSONObject.toKotlinMap(): Map<String, Any?> {
        val out = LinkedHashMap<String, Any?>()
        val keys = keys()
        while (keys.hasNext()) {
            val key = keys.next()
            out[key] = unwrap(opt(key))
        }
        return out
    }

    private fun unwrap(value: Any?): Any? = when (value) {
        null, JSONObject.NULL -> null
        is JSONObject -> value.toKotlinMap()
        is JSONArray -> (0 until value.length()).map { unwrap(value.opt(it)) }
        else -> value
    }

    fun catalog(): Map<String, Any?> = parse(api.callAttr("catalog"))

    fun cached(): Map<String, Any?> = parse(api.callAttr("cached"))

    fun setVisible(programId: String, visible: Boolean): Map<String, Any?> =
        parse(api.callAttr("set_visible", programId, visible))

    fun setChoice(programId: String, key: String, enabled: Boolean): Map<String, Any?> =
        parse(api.callAttr("set_choice", programId, key, enabled))

    fun status(): Map<String, Any?> = parse(api.callAttr("status"))

    fun inspect(email: String, password: String): Map<String, Any?> =
        parse(api.callAttr("inspect", email, password))

    fun start(programId: String, basket: String, confirm: String, email: String, password: String): Map<String, Any?> =
        parse(api.callAttr("start", programId, basket, confirm, email, password))

    fun stop(confirm: String, email: String, password: String): Map<String, Any?> =
        parse(api.callAttr("stop", confirm, email, password))
}
