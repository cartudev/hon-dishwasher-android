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

    fun status(): Map<String, Any?> = api.callAttr("status").asMap()

    fun inspect(email: String, password: String): Map<String, Any?> =
        api.callAttr("inspect", email, password).asMap()

    fun start(programId: String, basket: String, confirm: String, email: String, password: String): Map<String, Any?> =
        api.callAttr("start", programId, basket, confirm, email, password).asMap()

    fun stop(confirm: String, email: String, password: String): Map<String, Any?> =
        api.callAttr("stop", confirm, email, password).asMap()
}
