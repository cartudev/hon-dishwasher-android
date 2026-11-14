pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
        // Chaquopy's Android-compiled Python packages (aiohttp, ...).
        maven { url = uri("https://chaquo.com/maven") }
    }
}

rootProject.name = "hon-dishwasher"
include(":app")
