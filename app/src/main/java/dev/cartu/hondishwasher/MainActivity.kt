package dev.cartu.hondishwasher

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

val Bg = Color(0xFF0e0f13)
val Card = Color(0xFF16171d)
val CardBorder = Color(0xFF26272e)
val Text2 = Color(0xFF9aa0ab)
val Accent = Color(0xFF7aa2ff)

@Composable
fun honFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = Color.White,
    unfocusedTextColor = Color.White,
    disabledTextColor = Text2,
    cursorColor = Accent,
    focusedContainerColor = Card,
    unfocusedContainerColor = Card,
    focusedBorderColor = Accent,
    unfocusedBorderColor = CardBorder,
    focusedLabelColor = Accent,
    unfocusedLabelColor = Text2,
)

private val HonScheme = darkColorScheme(
    primary = Accent,
    onPrimary = Color.White,
    background = Bg,
    onBackground = Color.White,
    surface = Card,
    onSurface = Color.White,
    surfaceVariant = Card,
    onSurfaceVariant = Text2,
    outline = CardBorder,
)

enum class Screen { Home, Program, Review, Settings, Stop }

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { AppRoot() }
    }
}

@Composable
fun AppRoot() {
    var screen by remember { mutableStateOf(Screen.Home) }
    var selected by remember { mutableStateOf("") }
    var basket by remember { mutableStateOf("off") }
    var snapshot by remember { mutableStateOf<Map<String, Any?>?>(null) }
    var programs by remember { mutableStateOf(listOf<Map<String, Any?>>()) }
    var status by remember { mutableStateOf("Cargando ciclos…") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val focus = LocalFocusManager.current

    fun refresh() {
        if (busy) return
        busy = true
        status = "Consultando el aparato (solo lectura)…"
        scope.launch(Dispatchers.IO) {
            val result = runCatching {
                PythonApi.inspect(Creds.email(context), Creds.password(context))
            }.getOrElse { mapOf("ok" to false, "error" to (it.message ?: "failed")) }
            withContext(Dispatchers.Main) {
                busy = false
                if (result["ok"] == true) {
                    snapshot = result
                    status = "Aparato consultado · solo lectura"
                    val order = (result["profileOrder"] as? List<*>)?.filterIsInstance<String>() ?: emptyList()
                    if (order.isNotEmpty() && selected !in order) selected = order.first()
                } else {
                    status = result["error"]?.toString() ?: "failed"
                }
            }
        }
    }

    fun goHome() {
        focus.clearFocus()
        screen = Screen.Home
    }

    fun toggleVisible(id: String, on: Boolean) {
        programs = programs.map { program ->
            if (program["id"] == id) program.toMutableMap().apply { put("visible", on) } else program
        }
        scope.launch(Dispatchers.IO) { runCatching { PythonApi.setVisible(id, on) } }
    }

    fun toggleChoice(id: String, key: String, on: Boolean) {
        programs = programs.map { program ->
            if (program["id"] != id) program
            else program.toMutableMap().apply {
                val required = (program["required"] as? List<*>)?.map { option ->
                    val map = (option as? Map<*, *>)?.entries
                        ?.associate { it.key.toString() to it.value }
                        ?.toMutableMap() ?: return@map option
                    if (map["key"] == key) map["enabled"] = on
                    map
                }
                put("required", required)
            }
        }
        scope.launch(Dispatchers.IO) { runCatching { PythonApi.setChoice(id, key, on) } }
    }

    // Cache first. The live query is slow, so it runs only when nothing is saved
    // yet, or when the user taps Actualizar.
    LaunchedEffect(Unit) {
        val listed = withContext(Dispatchers.IO) { runCatching { PythonApi.catalog() }.getOrNull() }
        val saved = withContext(Dispatchers.IO) { runCatching { PythonApi.cached() }.getOrNull() }
        programs = (listed?.get("programs") as? List<*>)?.mapNotNull { item ->
            (item as? Map<*, *>)?.entries?.associate { it.key.toString() to it.value }
        } ?: emptyList()
        if (saved?.get("ok") == true) {
            snapshot = saved
            status = "Última consulta guardada. Actualizar vuelve a consultar el aparato."
        } else if (Creds.saved(context)) {
            refresh()
        } else {
            status = "Faltan las credenciales. Abrí Configuración."
        }
    }

    BackHandler(enabled = screen != Screen.Home) {
        screen = if (screen == Screen.Review) Screen.Program else Screen.Home
        focus.clearFocus()
    }

    MaterialTheme(colorScheme = HonScheme) {
    Surface(color = Bg) {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp)
                .imePadding(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Column {
                Text("Candy · hOn", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                Text(
                    (snapshot?.get("model") as? String)?.takeIf { it.isNotBlank() } ?: "CF 6C4F1PS-12",
                    fontSize = 13.sp, color = Text2,
                )
            }

            when (screen) {
                Screen.Home -> HomeScreen(snapshot, programs, busy, status, onSelect = { id ->
                    selected = id; basket = "off"; screen = Screen.Program
                }, onRefresh = { refresh() }, onSettings = { screen = Screen.Settings })
                Screen.Program -> snapshot?.get("profiles")?.let { profiles ->
                    ProgramScreen(profiles, programs, selected, basket, onBasket = { basket = it },
                        onToggle = { key, on -> toggleChoice(selected, key, on) },
                        onBack = { goHome() }, onReview = { screen = Screen.Review })
                }
                Screen.Review -> ReviewScreen(snapshot, programs, selected, basket,
                    onBack = { screen = Screen.Program },
                    onStart = { confirm ->
                        busy = true
                        status = "Revalidando y arrancando…"
                        scope.launch(Dispatchers.IO) {
                            val result = runCatching {
                                PythonApi.start(selected, basket, confirm, Creds.email(context), Creds.password(context))
                            }.getOrElse { mapOf("ok" to false, "error" to (it.message ?: "failed")) }
                            withContext(Dispatchers.Main) {
                                busy = false
                                status = result["error"]?.toString() ?: "hOn aceptó el inicio de $selected."
                                if (result["ok"] == true) screen = Screen.Home
                                refresh()
                            }
                        }
                    })
                Screen.Settings -> SettingsScreen(
                    programs = programs,
                    onVisible = { id, on -> toggleVisible(id, on) },
                    onChoice = { id, key, on -> toggleChoice(id, key, on) },
                    onBack = { goHome() },
                    onSave = {
                        goHome()
                        if (snapshot == null) refresh()
                    },
                )
                Screen.Stop -> StopScreen(snapshot,
                    onBack = { goHome() },
                    onStop = { confirm ->
                        busy = true
                        scope.launch(Dispatchers.IO) {
                            val result = runCatching {
                                PythonApi.stop(confirm, Creds.email(context), Creds.password(context))
                            }.getOrElse { mapOf("ok" to false, "error" to (it.message ?: "failed")) }
                            withContext(Dispatchers.Main) {
                                busy = false
                                status = result["error"]?.toString() ?: "hOn aceptó detener el ciclo."
                                if (result["ok"] == true) screen = Screen.Home
                                refresh()
                            }
                        }
                    })
            }

            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (busy) "◌" else "●", color = if (busy) Accent else Text2)
                Text(status, fontSize = 12.sp, color = Text2)
            }
        }
    }
    }
}

@Composable
fun HomeScreen(
    snapshot: Map<String, Any?>?,
    programs: List<Map<String, Any?>>,
    busy: Boolean,
    status: String,
    onSelect: (String) -> Unit,
    onRefresh: () -> Unit,
    onSettings: () -> Unit,
) {
    val running = snapshot?.get("running") == true
    val remaining = snapshot?.get("remaining_time")?.toString()
    val hidden = programs.filter { it["visible"] == false }.mapNotNull { it["id"]?.toString() }.toSet()
    val order = ((snapshot?.get("profileOrder") as? List<*>)?.filterIsInstance<String>() ?: emptyList())
        .filter { it !in hidden }
    val profiles = snapshot?.get("profiles") as? Map<*, *> ?: emptyMap<Any, Any>()

    if (running) {
        Column(Modifier.fillMaxWidth().background(Card, RoundedCornerShape(14.dp)).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("CICLO EN CURSO", fontSize = 12.sp, color = Text2)
                (snapshot?.get("program") as? String)?.let { Text(it.uppercase(), fontSize = 11.sp, color = Text2) }
            }
            Text(if (remaining != null) "Quedan $remaining min" else "El aparato no informa tiempo restante",
                fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = Accent)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onRefresh, enabled = !busy) { Text("Actualizar") }
            }
        }
    }

    when {
        order.isEmpty() && busy -> Text("Consultando el aparato para listar programas…", color = Text2)
        order.isEmpty() && !busy -> Text(
            if (hidden.isNotEmpty() && snapshot != null) "No hay ciclos visibles; activá alguno en Configuración."
            else "Sin datos del aparato; mirá el estado abajo.",
            color = Text2,
        )
        else -> order.forEach { id ->
            val info = profiles[id] as? Map<*, *> ?: return@forEach
            val available = info["available"] == true
            Box(Modifier.fillMaxWidth().background(Card, RoundedCornerShape(14.dp))
                .clickable(enabled = available) { onSelect(id) }
                .padding(14.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(info["label"]?.toString() ?: id, fontSize = 16.sp, color = Color.White)
                    Text(if (available) "Disponible en el esquema" else "No disponible",
                        fontSize = 12.sp, color = if (available) Accent else Text2)
                }
            }
        }
    }

    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = onRefresh, enabled = !busy) { Text("Actualizar") }
        OutlinedButton(onClick = onSettings) { Text("Configuración") }
    }
}

@Composable
fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = Color.White)
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
fun ProgramScreen(
    profiles: Any?,
    programs: List<Map<String, Any?>>,
    selected: String,
    basket: String,
    onBasket: (String) -> Unit,
    onToggle: (String, Boolean) -> Unit,
    onBack: () -> Unit,
    onReview: () -> Unit,
) {
    val info = (profiles as? Map<*, *>)?.get(selected) as? Map<*, *> ?: return
    val available = info["available"] == true
    val remembered = (programs.find { it["id"] == selected }?.get("required") as? List<*>)
        ?.mapNotNull { option -> (option as? Map<*, *>)?.entries?.associate { it.key.toString() to it.value } }
        ?: emptyList()
    val options = (info["required"] as? List<*>)?.filterIsInstance<Map<*, *>>() ?: emptyList()
    val basketChoices = ((info["basket"] as? Map<*, *>)?.get("choices") as? List<*>)?.filterIsInstance<String>() ?: emptyList()

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Column(Modifier.fillMaxWidth().background(Card, RoundedCornerShape(14.dp)).padding(14.dp)) {
            Text("PROGRAMA — ${info["label"]}", color = Color.White)
            Text(info["reason"]?.toString()?.ifBlank {
                "código de programa hOn: ${info["code"]}"
            } ?: "", fontSize = 13.sp, color = Text2)
        }

        Text("OPCIONES RECORDADAS (SE ENVÍAN COMO ESTÁN)", fontSize = 12.sp, color = Text2)
        options.forEach { option ->
            val key = option["key"]?.toString() ?: return@forEach
            val enabled = remembered.find { it["key"] == key }?.get("enabled") as? Boolean
                ?: (option["enabled"] == true)
            SwitchRow(option["label"]?.toString() ?: key, enabled) { onToggle(key, it) }
        }

        Text("MEDIA CARGA (OPCIONAL)", fontSize = 12.sp, color = Text2)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("off" to "Ninguna", "upper" to "Canasta superior", "lower" to "Canasta inferior").forEach { (value, label) ->
                val allowed = value == "off" || value in basketChoices
                Box(Modifier.background(if (basket == value && allowed) Accent else Card, RoundedCornerShape(15.dp))
                    .clickable(enabled = allowed) { onBasket(value) }
                    .padding(horizontal = 12.dp, vertical = 6.dp)) {
                    Text(label, color = if (basket == value && allowed) Color.White else Text2, fontSize = 13.sp)
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onBack) { Text("Volver") }
            Button(onClick = onReview, enabled = available) { Text("Revisar…") }
        }
    }
}

@Composable
fun ReviewScreen(snapshot: Map<String, Any?>?, programs: List<Map<String, Any?>>, selected: String, basket: String, onBack: () -> Unit, onStart: (String) -> Unit) {
    val profiles = snapshot?.get("profiles") as? Map<*, *>
    val info = profiles?.get(selected) as? Map<*, *>
    val remoteReady = snapshot?.get("remote_ready") == true
    var confirm by remember { mutableStateOf("") }
    val options = ((programs.find { it["id"] == selected }?.get("required") as? List<*>)
        ?.mapNotNull { option -> (option as? Map<*, *>)?.entries?.associate { it.key.toString() to it.value } }
        ?: emptyList())
        .filter { it["enabled"] != false }
        .mapNotNull { it["label"]?.toString() }
        .joinToString(" · ")

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("REVISIÓN — TODAVÍA NO SE ENVIÓ NADA", fontSize = 12.sp, color = Text2)
        Column(Modifier.fillMaxWidth().background(Card, RoundedCornerShape(14.dp)).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("Programa: ${info?.get("label")} (${info?.get("code") ?: "sin confirmar"})", color = Color.White)
            Text("Opciones: $options", color = Color.White)
            Text("Media carga: $basket", color = Color.White)
            Text("Control remoto: ${if (remoteReady) "listo" else "no verificado / no listo"}", color = Color.White)
        }
        Text("Escribí INICIAR para habilitar el envío", fontSize = 13.sp, color = Text2)
        OutlinedTextField(value = confirm, onValueChange = { confirm = it },
            modifier = Modifier.fillMaxWidth(), singleLine = true, colors = honFieldColors())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { onBack(); }) { Text("Cancelar") }
            Button(onClick = { onStart(confirm) }, enabled = confirm.trim() == "INICIAR") { Text("Iniciar ciclo") }
        }
    }
}

@Composable
fun SettingsScreen(
    programs: List<Map<String, Any?>>,
    onVisible: (String, Boolean) -> Unit,
    onChoice: (String, String, Boolean) -> Unit,
    onBack: () -> Unit,
    onSave: () -> Unit,
) {
    val context = LocalContext.current
    var email by remember { mutableStateOf(Creds.email(context)) }
    var password by remember { mutableStateOf("") }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("CONFIGURACIÓN — CUENTA hOn", fontSize = 12.sp, color = Text2)
        OutlinedTextField(value = email, onValueChange = { email = it }, label = { Text("Correo hOn") },
            modifier = Modifier.fillMaxWidth(), singleLine = true, colors = honFieldColors())
        OutlinedTextField(value = password, onValueChange = { password = it },
            label = { Text("Contraseña (se guarda cifrada)") }, modifier = Modifier.fillMaxWidth(), singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            colors = honFieldColors())

        Text("CICLOS EN EL INICIO", fontSize = 12.sp, color = Text2)
        if (programs.isEmpty()) {
            Text("No hay ciclos en el menú.", color = Text2, fontSize = 13.sp)
        }
        programs.forEach { program ->
            val id = program["id"]?.toString() ?: return@forEach
            val label = program["label"]?.toString() ?: id
            SwitchRow(label, program["visible"] != false) { onVisible(id, it) }
            val required = (program["required"] as? List<*>)?.mapNotNull { option ->
                (option as? Map<*, *>)?.entries?.associate { it.key.toString() to it.value }
            } ?: emptyList()
            required.forEach { option ->
                val key = option["key"]?.toString() ?: return@forEach
                SwitchRow("    ${option["label"] ?: key}", option["enabled"] != false) { onChoice(id, key, it) }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onBack) { Text("Volver") }
            Button(enabled = email.contains("@") && password.isNotEmpty(), onClick = {
                Creds.save(context, email.trim(), password)
                onSave()
            }) { Text("Guardar") }
        }
    }
}

@Composable
fun StopScreen(snapshot: Map<String, Any?>?, onBack: () -> Unit, onStop: (String) -> Unit) {
    var confirm by remember { mutableStateOf("") }
    val remaining = snapshot?.get("remaining_time")?.toString()
    val code = snapshot?.get("pr_code")?.toString() ?: "?"

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("DETENER — TODAVÍA NO SE ENVIÓ NADA", fontSize = 12.sp, color = Text2)
        Column(Modifier.fillMaxWidth().background(Card, RoundedCornerShape(14.dp)).padding(14.dp)) {
            Text(if (remaining != null) "Quedan $remaining min" else "El aparato no informa tiempo restante",
                fontSize = 20.sp, color = Accent)
            Text("Ciclo prCode $code en curso", color = Color.White)
        }
        Text("Escribí DETENER para habilitar la parada", fontSize = 13.sp, color = Text2)
        OutlinedTextField(value = confirm, onValueChange = { confirm = it },
            modifier = Modifier.fillMaxWidth(), singleLine = true, colors = honFieldColors())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onBack) { Text("Volver") }
            Button(onClick = { onStop(confirm) }, enabled = confirm.trim() == "DETENER") { Text("Detener ciclo") }
        }
    }
}
