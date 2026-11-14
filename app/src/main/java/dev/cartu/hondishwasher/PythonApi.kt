package dev.cartu.hondishwasher

import android.app.Application
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
    }
}

/** Calls into app/src/main/python (backend.py through mobile_api.py). */
object PythonApi {
    private val api: PyObject by lazy {
        Python.getInstance().getModule("mobile_api")
    }

    /** Chaquopy 15's toJava(Map/HashMap) rejects plain dicts. Walk asMap/asList. */
    private fun PyObject.toKotlin(): Any? = when (type().toString()) {
        "<class 'NoneType'>" -> null
        "<class 'bool'>" -> toBoolean()
        "<class 'int'>" -> toLong()
        "<class 'float'>" -> toDouble()
        "<class 'str'>" -> toString()
        "<class 'dict'>" -> asMap().entries.associate { it.key.toString() to it.value.toKotlin() }
        "<class 'list'>" -> asList().map { it.toKotlin() }
        else -> toString()
    }

    private fun dictOf(result: PyObject): Map<String, Any?> =
        result.toKotlin() as? Map<String, Any?> ?: emptyMap()

    fun status(): Map<String, Any?> = dictOf(api.callAttr("status"))

    fun inspect(email: String, password: String): Map<String, Any?> =
        dictOf(api.callAttr("inspect", email, password))

    fun start(programId: String, basket: String, confirm: String, email: String, password: String): Map<String, Any?> =
        dictOf(api.callAttr("start", programId, basket, confirm, email, password))

    fun stop(confirm: String, email: String, password: String): Map<String, Any?> =
        dictOf(api.callAttr("stop", confirm, email, password))
}
