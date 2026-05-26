"""Real-ESRGAN upscaling helper.

Mirrors the lazy-session pattern used for background removal: keep one
RealESRGANer per (model, half, tile) combo so model weights are loaded
once and reused across requests.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, Tuple

import numpy as np
from PIL import Image

# (url, netscale, arch, arch_kwargs)
MODEL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "RealESRGAN_x4plus": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        "netscale": 4,
        "arch": "rrdb",
        "num_block": 23,
    },
    "RealESRNet_x4plus": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.1/RealESRNet_x4plus.pth",
        "netscale": 4,
        "arch": "rrdb",
        "num_block": 23,
    },
    "RealESRGAN_x4plus_anime_6B": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        "netscale": 4,
        "arch": "rrdb",
        "num_block": 6,
    },
    "RealESRGAN_x2plus": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
        "netscale": 2,
        "arch": "rrdb",
        "num_block": 23,
    },
    "realesr-animevideov3": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth",
        "netscale": 4,
        "arch": "srvgg",
    },
    "realesr-general-x4v3": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth",
        "netscale": 4,
        "arch": "srvgg",
    },
}

UPSCALE_MODEL_NAMES = tuple(MODEL_CONFIGS.keys())

_upsamplers: Dict[Tuple[str, bool, int, int, int], Any] = {}


def _build_upsampler(
    model_name: str, half: bool, tile: int, tile_pad: int, pre_pad: int
):
    from realesrgan import RealESRGANer

    cfg = MODEL_CONFIGS[model_name]
    netscale = cfg["netscale"]

    if cfg["arch"] == "rrdb":
        from basicsr.archs.rrdbnet_arch import RRDBNet

        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=cfg["num_block"],
            num_grow_ch=32,
            scale=netscale,
        )
    elif cfg["arch"] == "srvgg":
        from realesrgan.archs.srvgg_arch import SRVGGNetCompact

        model = SRVGGNetCompact(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_conv=32,
            upscale=netscale,
            act_type="prelu",
        )
    else:
        raise ValueError(f"Unknown arch for upscale model {model_name!r}")

    return RealESRGANer(
        scale=netscale,
        model_path=cfg["url"],
        model=model,
        tile=tile,
        tile_pad=tile_pad,
        pre_pad=pre_pad,
        half=half,
    )


def get_upsampler(
    model_name: str = "RealESRGAN_x4plus",
    half: bool = False,
    tile: int = 0,
    tile_pad: int = 10,
    pre_pad: int = 0,
):
    """Return a cached RealESRGANer, loading weights only on first use."""
    if model_name not in MODEL_CONFIGS:
        raise ValueError(
            f"Unknown upscale model {model_name!r}. "
            f"Available: {', '.join(MODEL_CONFIGS)}"
        )
    key = (model_name, half, tile, tile_pad, pre_pad)
    if key not in _upsamplers:
        _upsamplers[key] = _build_upsampler(model_name, half, tile, tile_pad, pre_pad)
    return _upsamplers[key]


def upscale_bytes(
    content: bytes,
    model_name: str = "RealESRGAN_x4plus",
    outscale: float = 4.0,
    half: bool = False,
    tile: int = 0,
    tile_pad: int = 10,
    pre_pad: int = 0,
) -> bytes:
    """Upscale an image given as raw bytes and return PNG bytes."""
    img = Image.open(BytesIO(content))
    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )
    img = img.convert("RGBA" if has_alpha else "RGB")
    img_np = np.array(img)

    # RealESRGANer.enhance expects BGR(A) numpy arrays (OpenCV convention).
    if img_np.shape[2] == 4:
        img_np = img_np[:, :, [2, 1, 0, 3]]
    else:
        img_np = img_np[:, :, [2, 1, 0]]

    upsampler = get_upsampler(
        model_name=model_name,
        half=half,
        tile=tile,
        tile_pad=tile_pad,
        pre_pad=pre_pad,
    )
    output, _ = upsampler.enhance(img_np, outscale=outscale)

    if output.shape[2] == 4:
        output = output[:, :, [2, 1, 0, 3]]
    else:
        output = output[:, :, [2, 1, 0]]

    buf = BytesIO()
    Image.fromarray(output).save(buf, format="PNG")
    return buf.getvalue()
