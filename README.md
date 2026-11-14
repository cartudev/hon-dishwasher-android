# hon-dishwasher (Android)

Mobile companion to the [hon-dishwasher](https://github.com/cartudev/hon-dishwasher)
tray widget: an Android app to control a **Candy CF 6C4F1PS-12** dishwasher
through the hOn API.

Same bases as the widget:

- **A vendored pyhOn** (`app/src/main/python/pyhon/`) embedded in the APK with
  [Chaquopy](https://chaquo.com/chaquopy/) — the generic schema engine, the
  `config/programs.json` menu, the remembered options, the explicit
  `INICIAR` / `DETENER` confirmation gates. The MQTT connection (awscrt, no
  Android wheel) is stubbed out: the app runs **stateless queries** and never
  opens the push channel.
- Credentials live in **EncryptedSharedPreferences** (the mobile equivalent of
  the keyring) and are passed to the backend on every call.
- Jetpack Compose screens mirroring the widget: home (with the cycle card and
  remaining time), program (remembered switches + half load), review, settings,
  stop.
- One process per operation, connecting and closing per call (no background
  sync).

## Build

Requirements: JDK 17, an Android SDK (Android Studio works out of the box) and
a Python interpreter **≤ 3.12** for the build (3.13+ breaks Chaquopy's bundled
pip). If your default `python3` is newer, point the build at one:

```bash
export CHAQUOPY_BUILD_PYTHON=/path/to/python3.12
./gradlew assembleDebug     # app/build/outputs/apk/debug/
```

The first build resolves pyhOn's dependencies against Chaquopy's Android wheel
repository; abiFilters are arm64-v8a (phones) and x86_64 (emulators).

## Repository layout

```
app/src/main/java/dev/cartu/hondishwasher/   Compose UI + Python bridge + secure credentials
app/src/main/python/                          backend.py, mobile_api.py, vendored pyhon/, config/
.github/workflows/ci.yml                      backend smoke test + Android build on every push
```

The backend CLI contract stays shared with the desktop widget: JSON in, JSON
out, explicit confirmations. Changes to the widget's `backend.py` and this
copy should travel together until it gets extracted into its own package.

## Status

Scaffold: screens and Python bridge in place; the vendored pyhon imports and
loads the menu. Next: validate the first build's Chaquopy wheel resolution and
try the APK on a device. Not yet on Google Play — sideload the debug APK.
