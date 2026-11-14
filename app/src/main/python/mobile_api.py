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

import backend


def _run(coroutine):
    try:
        return asyncio.run(coroutine)
    except backend.AppError as error:
        return {"ok": False, "code": error.code, "error": str(error)}
    except Exception:
        # Library tracebacks can contain account or device data. Never surface them.
        return {"ok": False, "code": "unexpected",
                "error": "Falló la operación con hOn; no se mostrarán datos sensibles."}


def status() -> dict:
    return backend.config_status()


def inspect(email: str, password: str) -> dict:
    return _run(backend.inspect(email, password))


def start(program_id: str, basket: str, confirm: str, email: str, password: str) -> dict:
    if confirm != "INICIAR":
        return {"ok": False, "code": "confirmation_required",
                "error": "Missing the explicit INICIAR confirmation; nothing was sent."}
    return _run(backend.start_program(program_id, basket, email, password))


def stop(confirm: str, email: str, password: str) -> dict:
    if confirm != "DETENER":
        return {"ok": False, "code": "confirmation_required",
                "error": "Missing the explicit DETENER confirmation; nothing was sent."}
    return _run(backend.stop_program(email, password))
