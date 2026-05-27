"""Real-ESRGAN upscaling helper.

Mirrors the lazy-session pattern used for background removal: keep one
RealESRGANer per (model, half, tile) combo so model weights are loaded
once and reused across requests.
"""

from __future__ import annotations

import gc
import logging
import math
from collections import OrderedDict
from io import BytesIO
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image

_logger = logging.getLogger(__name__)

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

# Cap input pixels to keep CPU/RAM in check. Tuned for 8GB M1 Air / CPU fp32.
# 1.5 MP ~= sqrt(1.5e6) ≈ 1224x1224. At outscale=4 that's ~4900x4900 output.
MAX_INPUT_MEGAPIXELS = 1.5

# Keep at most this many RealESRGANer instances alive. Each one holds the
# model weights in RAM, so unbounded caching across (tile, pad) variants
# is itself an OOM source.
_MAX_CACHED_UPSAMPLERS = 2

_upsamplers: "OrderedDict[Tuple[str, bool, int, int, int], Any]" = OrderedDict()


class UpscaleInputTooLarge(ValueError):
    """Raised when the input image exceeds MAX_INPUT_MEGAPIXELS."""


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
    model_name: str = "realesr-general-x4v3",
    half: bool = False,
    tile: int = 256,
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
    if key in _upsamplers:
        _upsamplers.move_to_end(key)
        return _upsamplers[key]

    upsampler = _build_upsampler(model_name, half, tile, tile_pad, pre_pad)
    _upsamplers[key] = upsampler
    while len(_upsamplers) > _MAX_CACHED_UPSAMPLERS:
        _upsamplers.popitem(last=False)
        gc.collect()
    return upsampler


def upscale_bytes(
    content: bytes,
    model_name: str = "realesr-general-x4v3",
    outscale: float = 4.0,
    half: bool = False,
    tile: int = 256,
    tile_pad: int = 10,
    pre_pad: int = 0,
    auto_resize: bool = True,
    resize_info: Optional[Dict[str, Tuple[int, int]]] = None,
) -> bytes:
    """Upscale an image given as raw bytes and return PNG bytes.

    If ``auto_resize`` is True and the input exceeds MAX_INPUT_MEGAPIXELS,
    the image is downscaled to fit before feeding the model. The caller can
    pass a ``resize_info`` dict; it will be populated with
    ``{"original": (w, h), "resized": (w, h)}`` when a resize happens.
    """
    if tile <= 0:
        tile = 256

    img = Image.open(BytesIO(content))
    original_size = (img.width, img.height)
    megapixels = (img.width * img.height) / 1_000_000
    if megapixels > MAX_INPUT_MEGAPIXELS:
        if not auto_resize:
            raise UpscaleInputTooLarge(
                f"Input image is {megapixels:.1f} MP ({img.width}x{img.height}); "
                f"max allowed is {MAX_INPUT_MEGAPIXELS} MP."
            )
        ratio = math.sqrt(MAX_INPUT_MEGAPIXELS / megapixels)
        new_w = max(1, int(img.width * ratio))
        new_h = max(1, int(img.height * ratio))
        _logger.warning(
            "Auto-resizing upscale input %dx%d (%.2f MP) -> %dx%d to fit %.2f MP cap",
            img.width, img.height, megapixels, new_w, new_h, MAX_INPUT_MEGAPIXELS,
        )
        img = img.resize((new_w, new_h), Image.LANCZOS)
        if resize_info is not None:
            resize_info["original"] = original_size
            resize_info["resized"] = (new_w, new_h)

    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )
    img = img.convert("RGBA" if has_alpha else "RGB")
    img_np = np.array(img)
    del img

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
    del img_np

    if output.shape[2] == 4:
        output = output[:, :, [2, 1, 0, 3]]
    else:
        output = output[:, :, [2, 1, 0]]

    buf = BytesIO()
    Image.fromarray(output).save(buf, format="PNG")
    del output
    gc.collect()
    return buf.getvalue()
