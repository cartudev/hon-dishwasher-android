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
    return asyncio.run(coroutine)


import sys
import traceback

_diag: dict = {"sys_path": sys.path}
for _module in ("aiohttp", "pyhon"):
    try:
        __import__(_module)
    except Exception:
        _diag[_module] = traceback.format_exc()

try:
    from pyhon import Hon  # noqa: F401 - the exact import connect_device performs
except Exception:
    _diag["pyhon.Hon"] = traceback.format_exc()


def diag() -> dict:
    # Device debugging: also drop the details to a file readable via run-as.
    try:
        from pathlib import Path
        Path("diag.txt").write_text(repr(_diag), encoding="utf-8")
    except Exception:
        pass
    return {"ok": True, "diag": _diag}


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
