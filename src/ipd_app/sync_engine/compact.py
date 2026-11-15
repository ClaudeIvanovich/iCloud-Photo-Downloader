"""JPG copies for the Compact folder (REQUIREMENTS.md, 6.3.1).

A copy is always made from the local original, never from the network.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from . import fs

_heif_lock = threading.Lock()
_heif_ready = False

_ORIENTATION = 0x0112
_MAKE = 0x010F
_MODEL = 0x0110
_DATETIME = 0x0132
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
# DateTimeOriginal, DateTimeDigitized and their UTC-offset / sub-second companions.
_DATE_TAGS = (0x9003, 0x9004, 0x9010, 0x9011, 0x9012, 0x9291, 0x9292)


def register_heif() -> None:
    """Teach Pillow to open HEIC/HEIF. Safe to call many times and from threads."""
    global _heif_ready
    if _heif_ready:
        return
    with _heif_lock:
        if not _heif_ready:
            import pillow_heif

            pillow_heif.register_heif_opener()
            _heif_ready = True


_srgb_bytes: bytes | None = None


def _srgb_profile() -> bytes:
    global _srgb_bytes
    if _srgb_bytes is None:
        from PIL import ImageCms

        _srgb_bytes = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    return _srgb_bytes


def _to_srgb(image):
    """Convert from the embedded profile (iPhone: Display P3) to sRGB."""
    from PIL import ImageCms

    icc = image.info.get("icc_profile")
    if not icc:
        return image
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        target = ImageCms.ImageCmsProfile(io.BytesIO(_srgb_profile()))
        return ImageCms.profileToProfile(image, source, target, outputMode="RGB")
    except Exception:  # noqa: BLE001 - a broken profile must not cost the user the copy
        return image


def _flatten(image):
    """RGB pixels; transparency is filled with white."""
    from PIL import Image

    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    if image.mode not in ("RGB", "L"):
        return image.convert("RGB")
    return image


def _copy_exif(source_exif):
    """Keep capture date, camera and GPS; reset Orientation to 1."""
    from PIL import Image

    result = Image.Exif()
    result[_ORIENTATION] = 1
    for tag in (_MAKE, _MODEL, _DATETIME):
        if source_exif.get(tag):
            result[tag] = source_exif[tag]
    source_ifd = source_exif.get_ifd(_EXIF_IFD)
    target_ifd = result.get_ifd(_EXIF_IFD)
    for tag in _DATE_TAGS:
        if tag in source_ifd:
            target_ifd[tag] = source_ifd[tag]
    gps = source_exif.get_ifd(_GPS_IFD)
    if gps:
        result.get_ifd(_GPS_IFD).update(gps)
    return result


def make_compact(
    source: Path,
    target: Path,
    long_side: int | None = 2048,
    quality: int = 85,
    mtime: float | None = None,
) -> bool:
    """Write a JPG copy of `source` to `target` through a temp file.

    Returns False when the target already exists (it is never replaced).
    Raises on unreadable or unsupported input.
    """
    from PIL import Image, ImageOps

    register_heif()
    if fs.exists(target):
        return False
    with Image.open(fs.long_path(source)) as opened:
        exif = _copy_exif(opened.getexif())
        image = ImageOps.exif_transpose(opened)  # rotate the pixels, not the tag
        image = _to_srgb(_flatten(image))
        if image.mode != "RGB":
            image = image.convert("RGB")
        if long_side and max(image.size) > long_side:
            image.thumbnail((long_side, long_side), Image.Resampling.LANCZOS)
        fs.ensure_dir(target.parent)
        part = fs.part_path(target)
        try:
            with open(fs.long_path(part), "wb") as handle:
                image.save(
                    handle,
                    "JPEG",
                    quality=quality,
                    optimize=True,
                    exif=exif.tobytes(),
                    icc_profile=_srgb_profile(),
                )
        except BaseException:
            fs.discard_part(part)
            raise
    if not fs.publish(part, target, mtime):
        fs.discard_part(part)
        return False
    return True
