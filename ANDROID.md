# Tích hợp Rembg Backend với Android (Kotlin + Jetpack Compose)

Hướng dẫn từng bước để gọi HTTP API của `rembg` backend từ ứng dụng Android viết bằng Kotlin và Jetpack Compose. Stack đề xuất: **Retrofit + OkHttp + Coroutines + Coil**.

---

## 1. Chuẩn bị backend

Chạy server cho phép truy cập từ điện thoại (cùng mạng LAN):

```bash
poetry run rembg s --host 0.0.0.0 --port 7000 --no-ui
```

Lấy IP máy đang chạy backend (ví dụ `192.168.1.10`). Trên Android emulator, dùng `10.0.2.2` để trỏ về `localhost` của máy host.

> **HTTP cleartext**: Backend mặc định chạy `http://` (không TLS). Android 9+ chặn cleartext mặc định — xem mục 4 để bật cho domain dev.

---

## 2. Dependencies (Gradle Kotlin DSL)

`app/build.gradle.kts`:

```kotlin
dependencies {
    // Compose
    implementation(platform("androidx.compose:compose-bom:2025.01.00"))
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.activity:activity-compose:1.9.3")

    // Networking
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    // Image loading (hiển thị PNG kết quả)
    implementation("io.coil-kt:coil-compose:2.7.0")

    // ViewModel
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
}
```

`AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET" />

<application
    android:usesCleartextTraffic="true"
    android:networkSecurityConfig="@xml/network_security_config"
    ...>
</application>
```

---

## 3. Network security config (cho phép HTTP dev)

`app/src/main/res/xml/network_security_config.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="true">10.0.2.2</domain>       <!-- emulator -->
        <domain includeSubdomains="true">192.168.1.10</domain>   <!-- LAN IP máy backend -->
    </domain-config>
</network-security-config>
```

---

## 4. Định nghĩa API client (Retrofit)

`RembgApi.kt`:

```kotlin
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.ResponseBody
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Query
import java.util.concurrent.TimeUnit

interface RembgApi {
    @Multipart
    @POST("api/remove")
    suspend fun removeBackground(
        @Part file: MultipartBody.Part,
        @Query("model") model: String = "u2net",
        @Query("a") alphaMatting: Boolean = false,
        @Query("af") foregroundThreshold: Int = 240,
        @Query("ab") backgroundThreshold: Int = 10,
        @Query("ae") erodeSize: Int = 10,
        @Query("om") onlyMask: Boolean = false,
        @Query("ppm") postProcessMask: Boolean = false,
        @Query("bgc") backgroundColor: String? = null, // "R,G,B,A"
    ): ResponseBody
}

object RembgClient {
    // Đổi base URL theo môi trường:
    //   - Emulator: http://10.0.2.2:7000/
    //   - Máy thật (LAN): http://192.168.1.10:7000/
    private const val BASE_URL = "http://10.0.2.2:7000/"

    val api: RembgApi by lazy {
        val client = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)   // model lần đầu có thể tải weights
            .writeTimeout(60, TimeUnit.SECONDS)
            .addInterceptor(HttpLoggingInterceptor().apply {
                level = HttpLoggingInterceptor.Level.HEADERS
            })
            .build()

        Retrofit.Builder()
            .baseUrl(BASE_URL)
            .client(client)
            .build()
            .create(RembgApi::class.java)
    }
}
```

---

## 5. Repository — đọc Uri, upload, nhận PNG

`RembgRepository.kt`:

```kotlin
import android.content.Context
import android.net.Uri
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream

class RembgRepository(private val appContext: Context) {

    suspend fun removeBackground(
        imageUri: Uri,
        model: String = "u2net",
        postProcess: Boolean = true,
        bgColor: String? = null,
    ): ByteArray {
        val bytes = appContext.contentResolver.openInputStream(imageUri)?.use { it.readBytes() }
            ?: error("Không đọc được ảnh đầu vào")

        val part = MultipartBody.Part.createFormData(
            name = "file",
            filename = "input.jpg",
            body = bytes.toRequestBody("image/*".toMediaTypeOrNull()),
        )

        val responseBody = RembgClient.api.removeBackground(
            file = part,
            model = model,
            postProcessMask = postProcess,
            backgroundColor = bgColor,
        )
        return responseBody.bytes()
    }
}
```

---

## 6. ViewModel

`RembgViewModel.kt`:

```kotlin
import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface RembgUiState {
    data object Idle : RembgUiState
    data object Loading : RembgUiState
    data class Success(val pngBytes: ByteArray) : RembgUiState
    data class Error(val message: String) : RembgUiState
}

class RembgViewModel(app: Application) : AndroidViewModel(app) {
    private val repo = RembgRepository(app.applicationContext)

    private val _state = MutableStateFlow<RembgUiState>(RembgUiState.Idle)
    val state: StateFlow<RembgUiState> = _state.asStateFlow()

    fun remove(uri: Uri, model: String = "u2net") {
        _state.value = RembgUiState.Loading
        viewModelScope.launch {
            runCatching { repo.removeBackground(uri, model = model) }
                .onSuccess { _state.value = RembgUiState.Success(it) }
                .onFailure { _state.value = RembgUiState.Error(it.message ?: "Lỗi không xác định") }
        }
    }
}
```

---

## 7. Compose UI — chọn ảnh, gọi API, hiển thị kết quả

`RembgScreen.kt`:

```kotlin
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import coil.request.ImageRequest
import androidx.compose.ui.platform.LocalContext

@Composable
fun RembgScreen(vm: RembgViewModel = viewModel()) {
    val state by vm.state.collectAsState()
    val ctx = LocalContext.current
    var selectedModel by rememberSaveable { mutableStateOf("u2net") }
    var pickedUri by remember { mutableStateOf<android.net.Uri?>(null) }

    val picker = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia()
    ) { uri ->
        if (uri != null) {
            pickedUri = uri
            vm.remove(uri, model = selectedModel)
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Rembg Demo", style = MaterialTheme.typography.headlineSmall)

        ModelDropdown(selected = selectedModel, onSelected = { selectedModel = it })

        Button(onClick = {
            picker.launch(
                androidx.activity.result.PickVisualMediaRequest(
                    ActivityResultContracts.PickVisualMedia.ImageOnly
                )
            )
        }) { Text("Chọn ảnh") }

        when (val s = state) {
            RembgUiState.Idle -> Text("Hãy chọn một ảnh để xoá nền.")
            RembgUiState.Loading -> {
                CircularProgressIndicator()
                Text("Đang xử lý… (lần đầu có thể mất ~30s để tải model)")
            }
            is RembgUiState.Error -> Text("Lỗi: ${s.message}", color = MaterialTheme.colorScheme.error)
            is RembgUiState.Success -> {
                AsyncImage(
                    model = ImageRequest.Builder(ctx).data(s.pngBytes).build(),
                    contentDescription = "Ảnh đã xoá nền",
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ModelDropdown(selected: String, onSelected: (String) -> Unit) {
    val models = listOf(
        "u2net", "u2netp", "u2net_human_seg", "silueta",
        "isnet-general-use", "birefnet-general", "birefnet-general-lite",
        "birefnet-portrait", "bria-rmbg",
    )
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = !expanded }) {
        TextField(
            readOnly = true,
            value = selected,
            onValueChange = {},
            label = { Text("Model") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier = Modifier.menuAnchor(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            models.forEach { m ->
                DropdownMenuItem(text = { Text(m) }, onClick = {
                    onSelected(m); expanded = false
                })
            }
        }
    }
}
```

---

## 8. MainActivity

```kotlin
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface { RembgScreen() }
            }
        }
    }
}
```

---

## 9. Lưu kết quả vào MediaStore (tuỳ chọn)

```kotlin
import android.content.ContentValues
import android.content.Context
import android.provider.MediaStore

fun saveToGallery(ctx: Context, pngBytes: ByteArray, displayName: String = "rembg_${System.currentTimeMillis()}.png") {
    val values = ContentValues().apply {
        put(MediaStore.Images.Media.DISPLAY_NAME, displayName)
        put(MediaStore.Images.Media.MIME_TYPE, "image/png")
        put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/Rembg")
    }
    val uri = ctx.contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
        ?: error("Không tạo được file đầu ra")
    ctx.contentResolver.openOutputStream(uri)?.use { it.write(pngBytes) }
}
```

---

## 10. Mẹo & lưu ý production

- **Lần đầu gọi mỗi model**: backend cần download weights → đặt `readTimeout` ≥ 60s. Có thể "warm-up" bằng cách gọi ngầm 1 request nhỏ khi app khởi động.
- **Resize trước khi upload**: ảnh điện thoại thường > 4MP. Nén/giảm cạnh dài về ~1500px để giảm thời gian inference và băng thông.
- **Background color**: dùng `bgc = "255,255,255,255"` để xuất nền trắng (tiện cho ảnh chân dung).
- **Không nhúng IP máy lập trình vào release**: dùng `BuildConfig` hoặc `flavors` để tách `BASE_URL` dev/staging/prod.
- **Production**: deploy backend sau HTTPS reverse proxy → bỏ `usesCleartextTraffic`, bỏ `network_security_config` cho domain prod.
- **Retry**: với lỗi `500` thử fallback sang model nhẹ hơn (`u2netp`, `birefnet-general-lite`).
- **Hủy request**: do dùng `suspend` + `viewModelScope`, khi user rời màn hình request tự cancel — không cần xử lý thêm.

Tham khảo thêm tham số API và danh sách model đầy đủ ở [`FRONTEND.md`](./FRONTEND.md).
