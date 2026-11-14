plugins {
    id("com.android.application")
    id("com.chaquo.python")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "dev.cartu.hondishwasher"
    compileSdk = 34

    defaultConfig {
        applicationId = "dev.cartu.hondishwasher"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "0.1.1"

        ndk {
            // arm64-v8a for phones; x86_64 for emulators.
            abiFilters += listOf("arm64-v8a", "x86_64")
            // Needed by Chaquopy to build source packages (awscrt) for Android.
            version = "27.2.12479018"
        }

        chaquopy {
            defaultConfig {
                version = "3.11"
                // CI: the runner's python3 (3.12 on ubuntu-24.04). Locally point
                // CHAQUOPY_BUILD_PYTHON at a <=3.12 interpreter (3.13+ breaks
                // Chaquopy's bundled pip: no `cgi` module).
                buildPython = listOf(System.getenv("CHAQUOPY_BUILD_PYTHON") ?: "python3")
                pip {
                    // pyhOn is vendored (awscrt has no Android wheel). Chaquopy's
                    // cp311 index tops out at yarl 1.9.3, which has no `Query`.
                    // aiohttp 3.10 imports that name and the app dies at startup
                    // with "pyhOn is not installed". 3.9.1 is the newest wheel
                    // that matches yarl 1.9.3.
                    install("aiohttp==3.9.1")
                    install("yarl==1.9.3")
                    install("typing-extensions")
                }
            }
        }
    }

    buildTypes {
        release {
            // Sideloading-friendly: signed with the debug key so the release APK
            // installs on any device without a distribution keystore.
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    buildFeatures {
        compose = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.09.00")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("androidx.datastore:datastore-preferences:1.1.1")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
}
