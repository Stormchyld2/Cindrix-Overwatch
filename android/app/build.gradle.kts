plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.cindrix.overwatch"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.cindrix.overwatch"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    // Signing: a release keystore from GitHub Actions secrets if provided, otherwise the keystore committed in
    // this repo. The committed key is NOT secret; it only keeps the signature stable so new builds install over old ones.
    signingConfigs {
        create("cindrix") {
            val ks = System.getenv("OVERWATCH_KEYSTORE_FILE")
            if (ks != null && ks.isNotBlank()) {
                storeFile = file(ks)
                storePassword = System.getenv("OVERWATCH_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("OVERWATCH_KEY_ALIAS")
                keyPassword = System.getenv("OVERWATCH_KEY_PASSWORD")
            } else {
                storeFile = file("cindrix-overwatch.keystore")
                storePassword = "android"
                keyAlias = "cindrixoverwatch"
                keyPassword = "android"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("cindrix")
        }
        debug {
            signingConfig = signingConfigs.getByName("cindrix")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    lint {
        checkReleaseBuilds = false
        abortOnError = false
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.core:core-splashscreen:1.0.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    // Google ML Kit: finds the language and translates on the phone. Language packs (about 30 MB each) are downloaded once.
    implementation("com.google.mlkit:translate:17.0.3")
    implementation("com.google.mlkit:language-id:17.0.6")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("net.sf.kxml:kxml2:2.3.0")
}
