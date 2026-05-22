# Hướng dẫn tích hợp Frontend với Rembg Backend

Tài liệu này mô tả cách gọi HTTP API của backend `rembg` từ phía frontend (web, mobile, hoặc bất kỳ HTTP client nào).

## 1. Chạy backend

Cài đặt và khởi chạy server (mặc định cổng `7000`):

```bash
poetry install --extras "cpu cli"
poetry run rembg s --host 0.0.0.0 --port 7000 --no-ui
```

Tuỳ chọn quan trọng của lệnh `rembg s`:

| Cờ | Mặc định | Ý nghĩa |
|---|---|---|
| `-h, --host` | `0.0.0.0` | Host bind. Đặt `127.0.0.1` nếu chỉ chạy local |
| `-p, --port` | `7000` | Cổng HTTP |
| `-t, --threads` | (không giới hạn) | Số worker xử lý song song |
| `--no-ui` | `false` | Tắt Gradio UI để giảm CPU idle (khuyến nghị khi chỉ dùng API) |
| `-l, --log_level` | `info` | Mức log của uvicorn |

Sau khi chạy:

- **Swagger UI**: `http://localhost:7000/api`
- **Gradio demo UI** (nếu không truyền `--no-ui`): `http://localhost:7000/`

## 2. Endpoints

Backend expose hai endpoint dưới prefix `/api/remove`.

### 2.1. `POST /api/remove` — upload ảnh trực tiếp (khuyến nghị cho frontend)

- **Content-Type**: `multipart/form-data`
- **Body field `file`**: byte stream của ảnh (PNG/JPEG/WEBP…)
- **Query params**: xem bảng tham số ở mục 3
- **Response**: `image/png` (ảnh đã xoá nền). Status `200` khi thành công.

### 2.2. `GET /api/remove?url=...` — tải ảnh từ URL công khai

- **Query param `url`**: URL `http(s)` của ảnh cần xử lý
- **Response**: `image/png`
- **Giới hạn bảo mật (SSRF guard)**: server từ chối URL trỏ tới IP nội bộ / loopback / link-local / reserved. Chỉ dùng được với ảnh public trên internet.

## 3. Tham số chung

Cả `GET` và `POST` đều dùng chung tập tham số sau (gửi qua **query string**; `POST` cũng chấp nhận một số trường qua form):

| Tham số | Kiểu | Mặc định | Mô tả |
|---|---|---|---|
| `model` | string | `u2net` | Model dùng để remove background. Xem danh sách ở mục 4 |
| `a` | bool | `false` | Bật Alpha Matting để biên mượt hơn (chậm hơn) |
| `af` | int (0–255) | `240` | Alpha Matting Foreground Threshold |
| `ab` | int (0–255) | `10` | Alpha Matting Background Threshold |
| `ae` | int (≥0) | `10` | Alpha Matting Erode Structure Size |
| `om` | bool | `false` | Chỉ trả về binary mask (PNG đen/trắng) |
| `ppm` | bool | `false` | Áp dụng morphological post-processing cho mask |
| `bgc` | string `"R,G,B,A"` | (rỗng) | Tô màu nền thay vì để trong suốt. VD `bgc=255,255,255,255` cho nền trắng |
| `extras` | string (JSON) | (rỗng) | Tham số bổ sung truyền vào session (ví dụ `model_path` cho `*_custom`) |

## 4. Danh sách model hỗ trợ

`u2net` (mặc định), `u2netp`, `u2net_human_seg`, `u2net_cloth_seg`, `u2net_custom`, `silueta`, `isnet-general-use` (`dis_general_use`), `isnet-anime` (`dis_anime`), `dis_custom`, `sam`, `birefnet-general`, `birefnet-general-lite`, `birefnet-portrait`, `birefnet-dis`, `birefnet-hrsod`, `birefnet-cod`, `birefnet-massive`, `bria-rmbg`, `ben_custom`.

> Lần đầu gọi một model, server sẽ download weights — request đầu tiên có thể mất vài giây đến vài chục giây tuỳ băng thông.

## 5. Ví dụ tích hợp frontend

### 5.1. JavaScript / TypeScript (Browser, `fetch`)

```ts
async function removeBackground(file: File): Promise<Blob> {
  const form = new FormData();
  form.append("file", file);

  const params = new URLSearchParams({
    model: "u2net",
    a: "false",
    ppm: "true",
  });

  const res = await fetch(
    `http://localhost:7000/api/remove?${params.toString()}`,
    { method: "POST", body: form },
  );

  if (!res.ok) {
    throw new Error(`Rembg error ${res.status}: ${await res.text()}`);
  }
  return await res.blob(); // image/png
}

// Hiển thị kết quả lên <img>
const blob = await removeBackground(inputFile);
const imgEl = document.querySelector("img#preview") as HTMLImageElement;
imgEl.src = URL.createObjectURL(blob);
```

### 5.2. React (component upload + preview)

```tsx
import { useState } from "react";

const API = import.meta.env.VITE_REMBG_URL ?? "http://localhost:7000";

export function BgRemover() {
  const [out, setOut] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API}/api/remove?model=birefnet-general`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) throw new Error(await res.text());
      setOut(URL.createObjectURL(await res.blob()));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <input type="file" accept="image/*" onChange={handleChange} />
      {loading && <p>Đang xử lý…</p>}
      {out && <img src={out} alt="result" />}
    </div>
  );
}
```

### 5.3. cURL (debug nhanh)

```bash
# POST file
curl -X POST "http://localhost:7000/api/remove?model=u2net&ppm=true" \
  -F "file=@./input.jpg" \
  --output output.png

# GET từ URL public
curl "http://localhost:7000/api/remove?url=https://example.com/photo.jpg&model=birefnet-general" \
  --output output.png

# Đổi nền sang trắng
curl -X POST "http://localhost:7000/api/remove?bgc=255,255,255,255" \
  -F "file=@./input.jpg" --output output.png
```

### 5.4. Next.js — proxy qua API route (ẩn backend khỏi browser)

Dùng khi không muốn lộ URL backend hoặc cần thêm auth ở giữa:

```ts
// app/api/remove/route.ts
export const runtime = "nodejs";

export async function POST(req: Request) {
  const form = await req.formData();
  const url = new URL("http://localhost:7000/api/remove");
  url.searchParams.set("model", "u2net");

  const res = await fetch(url, { method: "POST", body: form });
  return new Response(res.body, {
    status: res.status,
    headers: { "content-type": "image/png" },
  });
}
```

## 6. CORS

Backend bật `CORSMiddleware` với `allow_origins=["*"]` và `allow_credentials=false`, do đó frontend ở bất kỳ origin nào cũng gọi được. Nếu deploy production, **nên sửa lại whitelist** trong `rembg/commands/s_command.py` cho đúng domain của bạn.

## 7. Khuyến nghị production

- Chạy sau reverse proxy (Nginx / Caddy) có TLS; bind backend ở `127.0.0.1`.
- Đặt timeout phía frontend ≥ 60s cho request đầu tiên của mỗi model (tải weights). Có thể "warm-up" bằng cách gọi trước endpoint với 1 ảnh nhỏ khi server khởi động.
- Giới hạn kích thước upload ở reverse proxy (vd Nginx `client_max_body_size 20m`).
- Cache `session` theo `model` đã được backend xử lý sẵn — không cần khởi tạo lại từ frontend.
- Pre-download model trước khi mở traffic: `poetry run rembg d u2net birefnet-general`.
- Đặt `--threads` phù hợp số CPU core; với GPU, cài extras `gpu` thay vì `cpu`.

## 8. Mã lỗi thường gặp

| Status | Nguyên nhân | Cách xử lý frontend |
|---|---|---|
| `400` | `url` không hợp lệ hoặc trỏ tới IP nội bộ | Hiển thị thông báo "URL ảnh không hợp lệ" |
| `422` | Sai tham số (vd `model` không thuộc danh sách, `af` ngoài 0–255) | Validate input phía frontend trước khi gửi |
| `500` | Lỗi inference (ảnh hỏng, OOM, model fail) | Retry hoặc fallback model nhẹ hơn (`u2netp`, `birefnet-general-lite`) |
