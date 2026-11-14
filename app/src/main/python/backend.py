from __future__ import annotations

import asyncio
import getpass
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

SERVICE = "hon-dishwasher"

# Linux keeps the XDG layout; Windows/macOS use their own application-data folders.
if sys.platform == "win32":
    _CONFIG_BASE = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
elif sys.platform == "darwin":
    _CONFIG_BASE = Path.home() / "Library" / "Application Support"
else:
    _CONFIG_BASE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_HOME = _CONFIG_BASE
CONFIG_DIR = CONFIG_HOME / SERVICE
CONFIG_FILE = CONFIG_DIR / "config.json"
PROGRAMS_FILE = CONFIG_DIR / "programs.json"
# Android: the config travels next to the backend; the desktop widget keeps
# its own layout.
DEFAULT_PROGRAMS_FILE = Path(__file__).resolve().parent / "config" / "programs.json"
CACHE_FILE = CONFIG_DIR / "last-inspect.json"
CHOICES_FILE = CONFIG_DIR / "choices.json"
ACTIVE_MACHINE_MODES = {"2", "3", "4", "5"}


class AppError(Exception):
    def __init__(self, message: str, code: str = "app_error") -> None:
        super().__init__(message)
        self.code = code


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# --- Program configuration (the extensible base) ------------------------------


def validate_settings(data: Any, source: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AppError(f"{source}: el programs.json no es un objeto.", "programs_invalid")
    target = data.get("target")
    if not isinstance(target, dict) or not target.get("applianceType") or not target.get("model"):
        raise AppError(f"{source}: falta target con applianceType y model.", "programs_invalid")
    raw_programs = data.get("programs")
    if not isinstance(raw_programs, list) or not raw_programs:
        raise AppError(f"{source}: 'programs' debe ser una lista con al menos un programa.", "programs_invalid")
    programs: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    seen_aliases: set[str] = set()
    for raw in raw_programs:
        if not isinstance(raw, dict):
            raise AppError(f"{source}: cada programa debe ser un objeto.", "programs_invalid")
        program_id = str(raw.get("id", "")).strip()
        label = str(raw.get("label", "")).strip()
        aliases = raw.get("aliases")
        required = raw.get("required", [])
        if not program_id or not re.fullmatch(r"[a-z0-9_-]+", program_id):
            raise AppError(f"{source}: id inválido para un programa ({program_id!r}).", "programs_invalid")
        if program_id in programs:
            raise AppError(f"{source}: id de programa repetido ({program_id}).", "programs_invalid")
        if not label or not isinstance(aliases, list) or not aliases:
            raise AppError(f"{source}: {program_id} necesita label y aliases.", "programs_invalid")
        normalized = [normalize(alias) for alias in aliases]
        normalized = [alias for alias in normalized if alias]
        normalized_list = list(dict.fromkeys(normalized))
        if not normalized_list or (collides := set(normalized_list) & seen_aliases):
            raise AppError(f"{source}: alias repetido {sorted(collides)[0]!r} en {program_id}.", "programs_invalid")
        seen_aliases |= set(normalized_list)
        if not isinstance(required, list):
            raise AppError(f"{source}: required de {program_id} debe ser una lista.", "programs_invalid")
        parsed_required = []
        for option in required:
            if not isinstance(option, dict) or not option.get("key") or not option.get("label"):
                raise AppError(f"{source}: opciones de {program_id} necesitan key y label.", "programs_invalid")
            parsed_required.append({"key": str(option["key"]), "label": str(option["label"])})
        programs[program_id] = {
            "id": program_id,
            "label": label,
            # In declaration order: the first alias wins over schema variants.
            "aliases": normalized_list,
            "required": parsed_required,
            "basket": bool(raw.get("basket", False)),
        }
        order.append(program_id)
    return {
        "target": {"type": str(target["applianceType"]), "model": str(target["model"])},
        "programs": programs,
        "order": order,
    }


def load_settings() -> dict[str, Any]:
    # The user's override wins when present; if broken, report it and never guess.
    source = PROGRAMS_FILE if PROGRAMS_FILE.is_file() else DEFAULT_PROGRAMS_FILE
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AppError(f"No se pudo leer {source}: {error}", "programs_unreadable")
    return validate_settings(data, source)


SETTINGS = load_settings()


def reload_settings() -> None:
    global SETTINGS
    SETTINGS = load_settings()


# --- Credenciales ------------------------------------------------------------


def read_config() -> dict[str, Any]:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AppError("Faltan las credenciales. Abrí Configuración.", "config_missing")
    except (OSError, json.JSONDecodeError):
        raise AppError("No se pudo leer la configuración local.", "config_invalid")
    email = data.get("email") if isinstance(data, dict) else None
    if not isinstance(email, str) or not email.strip():
        raise AppError("La configuración no contiene una cuenta hOn válida.", "config_invalid")
    return {"email": email.strip()}


def secret_tool(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    if not shutil_which("secret-tool"):
        raise AppError("No está instalado secret-tool/libsecret.", "keyring_missing")
    try:
        return subprocess.run(
            ["secret-tool", *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        raise AppError("No se pudo acceder al keyring del sistema.", "keyring_unavailable")


def shutil_which(name: str) -> str | None:
    # Keep the backend dependency-free beyond pyhOn.
    from shutil import which

    return which(name)


# True when the Secret Service tool exists: Linux keeps using it, everything else
# goes through the keyring package. Tests flip this flag to pick the path.
USE_SECRET_TOOL = shutil_which("secret-tool") is not None


def credential_get(email: str) -> str:
    """Reads the password from the platform credential store: the Secret Service
    over secret-tool on Linux/secret-tool-capable systems, the `keyring` package
    (Windows Credential Manager, macOS Keychain, ...) everywhere else."""
    if USE_SECRET_TOOL:
        result = secret_tool("lookup", "service", SERVICE, "account", email)
        if result.returncode != 0 or not result.stdout:
            raise AppError("No encuentro la contraseña en el keyring. Abrí Configuración.", "secret_missing")
        return result.stdout.rstrip("\n")
    try:
        import keyring
    except ImportError:
        raise AppError("No hay almacén de credenciales disponible (instalá keyring).", "keyring_missing")
    password = keyring.get_password(SERVICE, email)
    if not password:
        raise AppError("No encuentro la contraseña en el keyring. Abrí Configuración.", "secret_missing")
    return password


def credential_store(email: str, password: str) -> None:
    if USE_SECRET_TOOL:
        result = secret_tool(
            "store",
            "--label=Contraseña de hOn (Candy dishwasher)",
            "service",
            SERVICE,
            "account",
            email,
            input_text=f"{password}\n",
        )
        if result.returncode != 0:
            raise AppError("El keyring rechazó el guardado; no se guardó la cuenta.", "keyring_write_failed")
        return
    try:
        import keyring
    except ImportError:
        raise AppError("No hay almacén de credenciales disponible (instalá keyring).", "keyring_missing")
    try:
        keyring.set_password(SERVICE, email, password)
    except Exception:
        raise AppError("El keyring rechazó el guardado; no se guardó la cuenta.", "keyring_write_failed")


def credential_present(email: str) -> bool:
    if USE_SECRET_TOOL:
        result = secret_tool("lookup", "service", SERVICE, "account", email)
        return result.returncode == 0 and bool(result.stdout)
    try:
        import keyring
    except ImportError:
        return False
    return bool(keyring.get_password(SERVICE, email))


def get_secret(email: str) -> str:
    return credential_get(email)


def save_config(email: str) -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
        temporary = CONFIG_FILE.with_suffix(".json.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as config:
            json.dump({"email": email, "version": 1}, config)
            config.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        raise AppError("No se pudo guardar la configuración local.", "config_write_failed")


def store_into_keyring(email: str, password: str) -> None:
    credential_store(email, password)


def store_credentials() -> dict[str, Any]:
    # The password arrives over stdin (JSON) from the Rune app, never argv nor disk.
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        raise AppError("La entrada para guardar credenciales no es válida.", "store_input_invalid")
    email = payload.get("email") if isinstance(payload, dict) else None
    password = payload.get("password") if isinstance(payload, dict) else None
    if not isinstance(email, str) or not email.strip() or "@" not in email:
        raise AppError("El correo no parece válido; no guardé nada.", "invalid_email")
    if not isinstance(password, str) or not password:
        raise AppError("La contraseña está vacía; no guardé nada.", "empty_password")
    email = email.strip()
    store_into_keyring(email, password)
    save_config(email)
    return {"ok": True, "saved": True}


def configure() -> None:
    print("Configuración de la cuenta hOn (se guarda solo en este equipo).")
    email = input("Correo de hOn: ").strip()
    if not email or "@" not in email:
        raise AppError("El correo no parece válido.", "invalid_email")
    password = getpass.getpass("Contraseña de hOn (oculta): ")
    if not password:
        raise AppError("La contraseña está vacía; no guardé nada.", "empty_password")
    store_into_keyring(email, password)
    save_config(email)
    print("Credenciales guardadas en el keyring del sistema.")


def config_status() -> dict[str, Any]:
    try:
        config = read_config()
    except AppError:
        return {"configured": False}
    return {"configured": credential_present(config["email"])}


# --- Generic schema engine ----------------------------------------------------


def bool_on(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parameter_values(parameter: Any) -> set[str]:
    typology = str(getattr(parameter, "typology", ""))
    if typology == "range":
        return set()
    try:
        return {str(value).strip().lower() for value in parameter.values}
    except (AttributeError, TypeError, ValueError):
        return set()


def allows(parameter: Any, value: str) -> bool:
    if parameter is None:
        return False
    wanted = str(value).strip().lower()
    typology = str(getattr(parameter, "typology", ""))
    if typology == "fixed":
        return str(getattr(parameter, "value", "")).strip().lower() == wanted
    if typology == "range":
        try:
            number = float(wanted)
            low = float(parameter.min)
            high = float(parameter.max)
            step = float(parameter.step)
            if step <= 0 or number < low - 1e-9 or number > high + 1e-9:
                return False
            index = (number - low) / step
            return abs(index - round(index)) < 1e-8
        except (AttributeError, TypeError, ValueError):
            return False
    return wanted in parameter_values(parameter)


def settable(parameter: Any, value: str) -> bool:
    return parameter is not None and str(getattr(parameter, "typology", "")) != "fixed" and allows(parameter, value)


def parameter_state(parameter: Any, value: str = "1") -> dict[str, Any]:
    if parameter is None:
        return {"supported": False, "reason": "no_expuesto"}
    pinned = str(getattr(parameter, "typology", "")) == "fixed"
    accepted = allows(parameter, value)
    return {
        "supported": accepted,
        "pinned": pinned,
        "reason": "fijo_en_1" if accepted and pinned else ("no_acepta_1" if not accepted else ""),
    }


def program_def(program_id: str) -> dict[str, Any]:
    if program_id not in SETTINGS["programs"]:
        raise AppError("Programa no admitido por esta app.", "profile_invalid")
    return SETTINGS["programs"][program_id]


def get_profile_category(start_command: Any, program: dict[str, Any]) -> tuple[str | None, Any | None]:
    categories = getattr(start_command, "categories", {}) or {}
    matches = {
        normalize(code): (str(code), category)
        for code, category in categories.items()
        if normalize(code) in program["aliases"]
    }
    if not matches:
        return None, None
    # El esquema puede traer variantes localizadas del mismo programa (`intensive` y
    # `Intensivo`, `prewash` y `Pre-lavado`); gana la del primer alias declarado.
    for alias in program["aliases"]:
        if alias in matches:
            return matches[alias]
    return next(iter(matches.values()))


def inspect_profile(start_command: Any, program: dict[str, Any]) -> dict[str, Any]:
    code, category = get_profile_category(start_command, program)
    if category is None:
        return {
            "id": program["id"],
            "label": program["label"],
            "available": False,
            "code": None,
            "reason": "El API no expone este programa en el esquema actual.",
            "required": [
                {"key": option["key"], "label": option["label"], "supported": False, "pinned": False, "enabled": choice_enabled(program["id"], option["key"]), "reason": "no_expuesto"}
                for option in program["required"]
            ],
            "basket": {"available": False, "choices": []},
        }

    params = getattr(category, "parameters", {}) or {}
    required = []
    for option in program["required"]:
        state = parameter_state(params.get(option["key"]), "1")
        required.append({"key": option["key"], "label": option["label"], "enabled": choice_enabled(program["id"], option["key"]), **state})
    # Availability and notices only over enabled options; a disabled one must
    # deshabilitada debe poder ir a 0 para poder garantizar el apagado.
    missing = [option["label"] for option in required if option["enabled"] and not option["supported"]]
    stuck = [option["label"] for option in required if not option["enabled"] and not settable(params.get(option["key"]), "0")]

    diverter = params.get("diverterLevel")
    half_load = params.get("halfLoad")
    basket_choices = []
    if program["basket"] and all(settable(diverter, value) for value in ("0", "1", "2")) and all(
        settable(half_load, value) for value in ("0", "1")
    ):
        basket_choices = ["off", "upper", "lower"]

    return {
        "id": program["id"],
        "label": program["label"],
        "available": not missing and not stuck,
        "code": code,
        "reason": "" if not missing and not stuck else "No disponibles: " + ", ".join(missing + stuck) + ".",
        "required": required,
        "basket": {
            "available": bool(basket_choices),
            "choices": basket_choices,
            "reason": "" if basket_choices else "Canasta superior/inferior no confirmada para este programa.",
        },
    }


async def connect_device(email: str | None = None, password: str | None = None) -> tuple[Any, Any]:
    """Connects to hOn. Mobile front-ends pass their own credentials; the CLI
    falls back to the local config + keyring."""
    try:
        from pyhon import Hon
    except ImportError as error:
        # Surface the real cause (which module failed) instead of swallowing it.
        raise AppError(f"pyhOn import failed ({error.__class__.__name__}: {error}).", "pyhon_missing")

    if not (email and password):
        config = read_config()
        email = config["email"]
        password = get_secret(email)
    try:
        hon = await Hon(email, password).__aenter__()
    except Exception as error:
        password = ""
        # Class only. pyhOn's auth errors embed redirect URLs and response bodies.
        raise AppError(f"hOn no permitió iniciar sesión ({error.__class__.__name__}).", "hon_connection_failed")
    password = ""
    target = SETTINGS["target"]
    matches = [
        appliance
        for appliance in hon.appliances
        if appliance.appliance_type == target["type"] and target["model"] in appliance.model_name
    ]
    if len(matches) != 1:
        await hon.__aexit__(None, None, None)
        raise AppError(
            f"Se esperaba exactamente un aparato {target['model']}; se encontraron {len(matches)}.",
            "device_not_unique",
        )
    return hon, matches[0]


def load_choices() -> dict[str, Any]:
    """Remembered choices: per-program option switches (default ON) and which
    cycles show on the home screen. Half load is NEVER remembered: it always
    resets to no half load.
    """
    try:
        data = json.loads(CHOICES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    options = data.get("options")
    if not isinstance(options, dict):
        options = {}
    hidden = data.get("hidden")
    if not isinstance(hidden, list):
        hidden = []
    return {"options": options, "hidden": [str(program) for program in hidden]}


def bind_storage(path: str) -> None:
    """Point cache and choices at a writable app directory.

    On Android, Path.home() is not the app files dir, so the desktop XDG path
    either is not writable or does not survive. The UI calls this at startup.
    """
    global CONFIG_DIR, CONFIG_FILE, PROGRAMS_FILE, CACHE_FILE, CHOICES_FILE
    CONFIG_DIR = Path(path) / "hon"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    PROGRAMS_FILE = CONFIG_DIR / "programs.json"
    CACHE_FILE = CONFIG_DIR / "last-inspect.json"
    CHOICES_FILE = CONFIG_DIR / "choices.json"
    # Java File, not pathlib: Chaquopy's Python FS does not always see the
    # app files directory the same way the Android context does.
    try:
        from java.io import File
        directory = File(str(CONFIG_DIR))
        directory.mkdirs()
    except Exception:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    reload_settings()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def save_choices(choices: dict[str, Any]) -> None:
    try:
        _write_json(CHOICES_FILE, choices)
    except OSError:
        pass


def choice_enabled(program_id: str, key: str) -> bool:
    options = load_choices()["options"]
    for_program = options.get(program_id)
    if not isinstance(for_program, dict):
        return True
    return bool(for_program.get(key, True))


def set_option_choice(program_id: str, key: str, enabled: bool) -> dict[str, Any]:
    if program_id not in SETTINGS["programs"]:
        raise AppError("Programa no admitido por esta app.", "profile_invalid")
    program = SETTINGS["programs"][program_id]
    if not any(option["key"] == key for option in program["required"]):
        raise AppError("Opción no admitida por este programa.", "option_invalid")
    choices = load_choices()
    for_program = choices["options"].get(program_id)
    if not isinstance(for_program, dict):
        for_program = {}
        choices["options"][program_id] = for_program
    for_program[key] = enabled
    save_choices(choices)
    _patch_cached_choices()
    return {"ok": True, "choices": choices}


def set_program_visible(program_id: str, visible: bool) -> dict[str, Any]:
    if program_id not in SETTINGS["programs"]:
        raise AppError("Programa no admitido por esta app.", "profile_invalid")
    choices = load_choices()
    hidden = [program for program in choices["hidden"] if program != program_id]
    if not visible:
        hidden.append(program_id)
    choices["hidden"] = hidden
    save_choices(choices)
    _patch_cached_choices()
    return {"ok": True, "choices": choices}


def program_visible(program_id: str) -> bool:
    return program_id not in load_choices()["hidden"]


def live_state(appliance: Any) -> dict[str, Any]:
    start = appliance.commands.get("startProgram")
    remote = {
        key: bool_on(appliance.get(key, None))
        for key in ("remoteCtrValid", "remoteActionable", "remoteVisible")
    }
    door = appliance.get("doorStatus", None)
    mode = appliance.get("machMode", None)
    # El tiempo restante llega como remainingTimeMM (minutos); el detalle del ciclo
    # sent (the cycle's fingerprint) lives in attributes.activity.attributes.
    activity = (appliance.attributes or {}).get("activity") or {}
    activity_params = activity.get("attributes") or {}
    remaining = appliance.get("remainingTimeMM", None)
    program_name = activity_params.get("programName")
    profiles = {}
    for program_id in SETTINGS["order"]:
        program = SETTINGS["programs"][program_id]
        if start:
            profiles[program_id] = inspect_profile(start, program)
        else:
            profiles[program_id] = {
                "id": program_id,
                "label": program["label"],
                "available": False,
                "code": None,
                "reason": "El dispositivo no expone startProgram.",
                "required": [
                    {"key": option["key"], "label": option["label"], "supported": False, "pinned": False, "reason": "no_expuesto"}
                    for option in program["required"]
                ],
                "basket": {"available": False, "choices": []},
            }
    return {
        "ok": True,
        "model": appliance.model_name,
        "remote": remote,
        "remote_ready": all(remote.values()),
        "door_status": None if door is None else str(door),
        "machine_mode": None if mode is None else str(mode),
        # `active` lo calcula pyhon del bloque activity (CYCLE en curso).
        "running": bool((appliance.attributes or {}).get("active")),
        "remaining_time": None if remaining is None else str(remaining),
        "pr_code": None if appliance.get("prCode", None) is None else str(appliance.get("prCode")),
        "program": None if not program_name else str(program_name),
        "profileOrder": list(SETTINGS["order"]),
        "profiles": profiles,
        "choices": load_choices(),
    }


def cycle_state(appliance: Any) -> dict[str, Any]:
    """Light cycle state, with the same keys the queries publish."""
    mode = appliance.get("machMode", None)
    remaining = appliance.get("remainingTimeMM", appliance.get("remainingTime", None))
    attributes = appliance.attributes or {}
    activity = attributes.get("activity") or {}
    activity_params = activity.get("attributes") or {}
    program_name = activity_params.get("programName")
    return {
        "ok": True,
        "kind": "cycle",
        "machine_mode": None if mode is None else str(mode),
        "running": bool(attributes.get("active")) or (mode is not None and str(mode) in ACTIVE_MACHINE_MODES),
        "remote_ready": bool_on(appliance.get("remoteCtrValid", None)),
        "door_status": None if appliance.get("doorStatus", None) is None else str(appliance.get("doorStatus")),
        "remaining_time": None if remaining is None else str(remaining),
        "pr_code": None if appliance.get("prCode", None) is None else str(appliance.get("prCode")),
        "program": None if not program_name else str(program_name),
    }


async def stop_program(email: str | None = None, password: str | None = None) -> dict[str, Any]:
    hon, appliance = await connect_device(email, password)
    try:
        remote = {key: appliance.get(key, None) for key in ("remoteCtrValid", "remoteActionable", "remoteVisible")}
        if not all(bool_on(value) for value in remote.values()):
            raise AppError("El control remoto no está habilitado/listo en el aparato.", "remote_not_ready")
        mode = appliance.get("machMode", None)
        if mode is None or str(mode) not in ACTIVE_MACHINE_MODES:
            raise AppError("El aparato no reporta un ciclo activo que detener.", "no_active_cycle")
        command = appliance.commands.get("stopProgram")
        if command is None:
            raise AppError("El aparato no expone el comando stopProgram.", "stop_missing")
        accepted = await command.send()
        if not accepted:
            raise AppError("hOn no aceptó el comando de detención.", "command_rejected")
        return {"ok": True, "stopped": True}
    finally:
        await hon.__aexit__(None, None, None)


def check_start_preconditions(appliance: Any, program_id: str, basket: str) -> tuple[Any, Any]:
    if basket not in {"off", "upper", "lower"}:
        raise AppError("Opción de media carga no válida.", "basket_invalid")
    program = program_def(program_id)

    remote = {key: appliance.get(key, None) for key in ("remoteCtrValid", "remoteActionable", "remoteVisible")}
    if not all(bool_on(value) for value in remote.values()):
        raise AppError("El control remoto no está habilitado/listo en el aparato.", "remote_not_ready")

    door = appliance.get("doorStatus", None)
    if door is not None and str(door).strip().lower() in {"1", "true", "open"}:
        raise AppError("hOn reporta la puerta física abierta. Cerrala y volvé a actualizar.", "door_open")

    mode = appliance.get("machMode", None)
    if mode is not None and str(mode) in ACTIVE_MACHINE_MODES:
        raise AppError("El aparato ya está en un ciclo o inicio diferido; no envié otro.", "cycle_active")

    start = appliance.commands.get("startProgram")
    if start is None:
        raise AppError("El aparato no expone startProgram.", "program_command_missing")
    code, category = get_profile_category(start, program)
    if code is None or category is None:
        raise AppError("El programa elegido no aparece inequívocamente en el esquema actual.", "program_missing")

    params = getattr(category, "parameters", {}) or {}
    for option in program["required"]:
        parameter = params.get(option["key"])
        if choice_enabled(program["id"], option["key"]):
            if not allows(parameter, "1"):
                raise AppError(f"El programa elegido no admite {option['label']}=1.", "required_option_unavailable")
        elif not settable(parameter, "0"):
            raise AppError(f"El programa no permite desactivar {option['label']} en su esquema actual.", "required_option_unavailable")

    diverter = params.get("diverterLevel")
    half_load = params.get("halfLoad")
    if basket != "off":
        requested_level = "1" if basket == "upper" else "2"
        if not program["basket"] or not settable(diverter, requested_level) or not settable(half_load, "1"):
            raise AppError("El programa no admite esa media carga según su esquema actual.", "basket_unavailable")
    else:
        for parameter in (diverter, half_load):
            if parameter is not None and str(getattr(parameter, "typology", "")) == "fixed":
                if not allows(parameter, "0"):
                    raise AppError("El programa fija una media carga y no permite desactivarla.", "basket_fixed_on")
            elif parameter is not None and not allows(parameter, "0"):
                raise AppError("El programa no permite garantizar la opción sin media carga.", "basket_off_unavailable")

    return start, category


async def inspect(email: str | None = None, password: str | None = None) -> dict[str, Any]:
    hon, appliance = await connect_device(email, password)
    try:
        state = live_state(appliance)
        save_cache(state)
        return state
    finally:
        await hon.__aexit__(None, None, None)


def save_cache(state: dict[str, Any]) -> None:
    # Appliance data (no credentials): the app lists instantly on the next start.
    try:
        _write_json(CACHE_FILE, state)
    except OSError:
        pass


def _patch_cached_choices() -> None:
    """Keep the saved inspect in step with switches changed after the query."""
    try:
        state = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(state, dict):
        return
    choices = load_choices()
    state["choices"] = choices
    profiles = state.get("profiles")
    if isinstance(profiles, dict):
        for program_id, info in profiles.items():
            if not isinstance(info, dict):
                continue
            required = info.get("required")
            if not isinstance(required, list):
                continue
            for option in required:
                if isinstance(option, dict) and option.get("key"):
                    option["enabled"] = choice_enabled(str(program_id), str(option["key"]))
    save_cache(state)


def catalog() -> dict[str, Any]:
    """Programs and remembered switches. No network: available before the first query."""
    choices = load_choices()
    hidden = set(choices["hidden"])
    programs = []
    for program_id in SETTINGS["order"]:
        program = SETTINGS["programs"][program_id]
        programs.append({
            "id": program_id,
            "label": program["label"],
            "visible": program_id not in hidden,
            "required": [
                {
                    "key": option["key"],
                    "label": option["label"],
                    "enabled": choice_enabled(program_id, option["key"]),
                }
                for option in program["required"]
            ],
        })
    return {"ok": True, "programs": programs}


def cached_inspect() -> dict[str, Any]:
    try:
        state = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AppError("Todavía no hay una consulta guardada.", "cache_missing")
    if not isinstance(state, dict) or not state.get("ok"):
        raise AppError("La consulta guardada no es válida.", "cache_invalid")
    state["cached"] = True
    return state


async def start_program(program_id: str, basket: str, email: str | None = None, password: str | None = None) -> dict[str, Any]:
    program = program_def(program_id)
    hon, appliance = await connect_device(email, password)
    try:
        base_command, _ = check_start_preconditions(appliance, program_id, basket)
        available = base_command.available_settings
        program_param = next(
            (available.get(name) for name in ("program", "prCode") if available.get(name)),
            None,
        )
        if program_param is None:
            raise AppError("El esquema no expone el selector de programa esperado.", "program_selector_missing")
        program_code, _ = get_profile_category(base_command, program)
        if program_code is None:
            raise AppError("El programa dejó de estar disponible durante la preparación.", "program_missing")
        program_param.value = program_code

        command = appliance.commands.get("startProgram")
        if command is None:
            raise AppError("No se pudo seleccionar el comando startProgram.", "program_command_missing")
        params = command.parameters

        for option in program["required"]:
            parameter = params.get(option["key"])
            if parameter is None:
                raise AppError(f"El comando activo perdió la opción {option['key']}; no envié nada.", "schema_changed")
            if str(getattr(parameter, "typology", "")) != "fixed":
                # Remembered choices: enabled = 1; disabled = explicit 0.
                parameter.value = "1" if choice_enabled(program["id"], option["key"]) else "0"

        diverter = params.get("diverterLevel")
        half_load = params.get("halfLoad")
        level = {"off": "0", "upper": "1", "lower": "2"}[basket]
        if basket != "off":
            if diverter is None or half_load is None:
                raise AppError("Faltan parámetros de media carga en el comando activo.", "schema_changed")
            diverter.value = level
            half_load.value = "1"
        else:
            if diverter is not None and str(getattr(diverter, "typology", "")) != "fixed":
                if allows(diverter, "0"):
                    diverter.value = "0"
            if half_load is not None and str(getattr(half_load, "typology", "")) != "fixed":
                if allows(half_load, "0"):
                    half_load.value = "0"

        # Guard against the category changing under us: serialize the selected profile's
        # command object, not the command reference obtained before pyhOn's category swap.
        selected = appliance.commands.get("startProgram")
        if selected is None or selected.category != command.category:
            raise AppError("El comando cambió mientras se preparaba; no envié nada.", "command_changed")
        accepted = await selected.send()
        if not accepted:
            raise AppError("hOn no aceptó el comando de inicio.", "command_rejected")
        return {"ok": True, "sent": True, "program": program["label"], "basket": basket}
    finally:
        await hon.__aexit__(None, None, None)


async def dispatch(args: list[str]) -> None:
    reload_settings()
    if not args:
        raise AppError("Falta una operación.", "usage")
    operation = args[0]
    if operation == "status":
        emit({"ok": True, **config_status()})
        return
    if operation == "store":
        emit(store_credentials())
        return
    if operation == "inspect":
        emit(await inspect())
        return
    if operation == "cached":
        emit(cached_inspect())
        return
    if operation == "choices":
        emit({"ok": True, **load_choices()})
        return
    if operation == "choice":
        if len(args) != 5 or args[1] != "set":
            raise AppError("Operación de elección incompleta.", "usage")
        emit(set_option_choice(args[2], args[3], args[4] == "1"))
        return
    if operation == "visible":
        if len(args) != 4 or args[1] != "set":
            raise AppError("Operación de visibilidad incompleta.", "usage")
        emit(set_program_visible(args[2], args[3] == "1"))
        return
    if operation == "start":
        if len(args) != 4 or args[3] != "INICIAR":
            raise AppError("Falta confirmación explícita; no envié ningún comando.", "confirmation_required")
        emit(await start_program(args[1], args[2]))
        return
    if operation == "stop":
        if len(args) != 2 or args[1] != "DETENER":
            raise AppError("Falta confirmación explícita; no envié ningún comando.", "confirmation_required")
        emit(await stop_program())
        return
    raise AppError("Operación desconocida.", "usage")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "configure":
        try:
            configure()
            return 0
        except AppError as error:
            print(str(error), file=sys.stderr)
            return 1
        except (EOFError, KeyboardInterrupt):
            print("\nConfiguración cancelada; no se envió nada.", file=sys.stderr)
            return 1

    try:
        asyncio.run(dispatch(sys.argv[1:]))
        return 0
    except AppError as error:
        emit({"ok": False, "code": error.code, "error": str(error)})
        return 1
    except KeyboardInterrupt:
        emit({"ok": False, "code": "cancelled", "error": "Operación cancelada."})
        return 1
    except Exception:
        # Avoid emitting exception details: library errors may contain user or device data.
        emit({"ok": False, "code": "unexpected", "error": "Falló la operación con hOn; no se mostrarán datos sensibles."})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
