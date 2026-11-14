"""Sync facade over backend.py for mobile front-ends (Chaquopy calls these
directly from Kotlin on a worker thread). Every call connects, does the work
and closes the connection.

Credentials come from the caller (the Android side keeps them in
EncryptedSharedPreferences); the keyring paths in backend.py are CLI-only.

The explicit-confirmation guards live here too: the UI must pass
confirm="INICIAR" / confirm="DETENER" exactly, like the CLI does.
"""

from __future__ import annotations

import asyncio
import json

import backend


def _json(payload) -> str:
    # Kotlin parses this. None becomes JSON null; the bridge must not see raw dicts.
    return json.dumps(payload, ensure_ascii=False)


def _run(coroutine):
    try:
        return asyncio.run(coroutine)
    except backend.AppError as error:
        return {"ok": False, "code": error.code, "error": str(error)}
    except Exception:
        # Library tracebacks can contain account or device data. Never surface them.
        return {"ok": False, "code": "unexpected",
                "error": "Falló la operación con hOn; no se mostrarán datos sensibles."}


def bind_storage(path: str) -> str:
    backend.bind_storage(path)
    return _json({"ok": True, "path": str(backend.CONFIG_DIR)})


def _storage() -> None:
    """Bind once, from the Android context, so cache survives even if the
    Application hook did not run before the first call."""
    if getattr(backend, "_storage_bound", False):
        return
    try:
        from com.chaquo.python import Python
        context = Python.getPlatform().getApplication()
        backend.bind_storage(str(context.getFilesDir().getAbsolutePath()))
        backend._storage_bound = True
    except Exception:
        import traceback
        try:
            from java import jclass
            jclass("android.util.Log").e("hon-storage", traceback.format_exc())
        except Exception:
            pass


def catalog() -> str:
    _storage()
    return _json(backend.catalog())


def cached() -> str:
    _storage()
    try:
        return _json(backend.cached_inspect())
    except backend.AppError as error:
        return _json({"ok": False, "code": error.code, "error": str(error)})


def set_visible(program_id: str, visible: bool) -> str:
    _storage()
    try:
        return _json(backend.set_program_visible(program_id, bool(visible)))
    except backend.AppError as error:
        return _json({"ok": False, "code": error.code, "error": str(error)})


def set_choice(program_id: str, key: str, enabled: bool) -> str:
    _storage()
    try:
        return _json(backend.set_option_choice(program_id, key, bool(enabled)))
    except backend.AppError as error:
        return _json({"ok": False, "code": error.code, "error": str(error)})


def status() -> str:
    return _json(backend.config_status())


def inspect(email: str, password: str) -> str:
    _storage()
    return _json(_run(backend.inspect(email, password)))


def start(program_id: str, basket: str, confirm: str, email: str, password: str) -> str:
    if confirm != "INICIAR":
        return _json({"ok": False, "code": "confirmation_required",
                      "error": "Falta la confirmación INICIAR; no se envió nada."})
    return _json(_run(backend.start_program(program_id, basket, email, password)))


def stop(confirm: str, email: str, password: str) -> str:
    if confirm != "DETENER":
        return _json({"ok": False, "code": "confirmation_required",
                      "error": "Falta la confirmación DETENER; no se envió nada."})
    return _json(_run(backend.stop_program(email, password)))
