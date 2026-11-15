"""JPG copies for the Compact folder (REQUIREMENTS.md, 6.3.1)."""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageCms

from conftest import image_bytes, make_exif
from ipd_app.sync_engine.compact import make_compact, register_heif


def convert(tmp_path, data: bytes, name: str = "src.JPG", **options):
    source = tmp_path / name
    source.write_bytes(data)
    target = tmp_path / "Compact" / "out.jpg"
    assert make_compact(source, target, **options) is True
    return target


def test_heic_becomes_a_plain_jpeg(tmp_path) -> None:
    register_heif()
    target = convert(tmp_path, image_bytes("HEIF", size=(320, 240)), "IMG_1.HEIC")
    with Image.open(target) as copy:
        assert copy.format == "JPEG" and copy.size == (320, 240)
    assert not list(tmp_path.rglob("*.part"))


def test_orientation_is_applied_to_pixels_and_reset(tmp_path) -> None:
    # 80x40 stored sideways: orientation 6 means "rotate 90 degrees clockwise to view".
    target = convert(tmp_path, image_bytes(size=(80, 40), exif=make_exif(orientation=6)))
    with Image.open(target) as copy:
        assert copy.size == (40, 80)
        assert copy.getexif()[0x0112] == 1


def test_capture_date_camera_and_gps_are_kept(tmp_path) -> None:
    exif = make_exif("2023:03:05 14:30:00", orientation=3, gps=True, model="iPhone 14")
    target = convert(tmp_path, image_bytes(exif=exif))
    with Image.open(target) as copy:
        result = copy.getexif()
        assert result.get_ifd(0x8769)[0x9003] == "2023:03:05 14:30:00"
        assert result[0x0110] == "iPhone 14" and result[0x010F] == "Apple"
        gps = result.get_ifd(0x8825)
        assert gps[1] == "N" and gps[3] == "E"
        assert [round(float(v)) for v in gps[2]] == [55, 45, 21]


@pytest.mark.parametrize(("long_side", "expected"), [(2048, (2048, 1024)), (1600, (1600, 800)), (None, (4000, 2000))])
def test_long_side_is_reduced(tmp_path, long_side, expected) -> None:
    target = convert(tmp_path, image_bytes(size=(4000, 2000)), long_side=long_side)
    with Image.open(target) as copy:
        assert copy.size == expected


def test_small_photos_are_not_enlarged(tmp_path) -> None:
    target = convert(tmp_path, image_bytes(size=(300, 200)), long_side=2048)
    with Image.open(target) as copy:
        assert copy.size == (300, 200)


def test_png_transparency_becomes_white(tmp_path) -> None:
    data = image_bytes("PNG", size=(20, 20), color=(255, 0, 0, 0), mode="RGBA")
    target = convert(tmp_path, data, "shot.PNG")
    with Image.open(target) as copy:
        assert copy.mode == "RGB"
        assert all(channel > 245 for channel in copy.getpixel((10, 10)))


def test_display_p3_is_converted_to_srgb(tmp_path) -> None:
    # A wide-gamut profile built from primaries close to Display P3.
    p3 = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    lab = Image.new("LAB", (16, 16), (128, 20, 20))
    buffer = io.BytesIO()
    lab.save(buffer, "TIFF", icc_profile=p3)
    target = convert(tmp_path, buffer.getvalue(), "wide.TIF")
    with Image.open(target) as copy:
        assert copy.mode == "RGB"
        embedded = ImageCms.ImageCmsProfile(io.BytesIO(copy.info["icc_profile"]))
        assert "sRGB" in ImageCms.getProfileDescription(embedded)


def test_quality_changes_the_file_size(tmp_path) -> None:
    noisy = Image.effect_noise((600, 400), 80).convert("RGB")
    buffer = io.BytesIO()
    noisy.save(buffer, "JPEG", quality=98)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    low = convert(tmp_path / "a", buffer.getvalue(), quality=60)
    high = convert(tmp_path / "b", buffer.getvalue(), quality=95)
    assert low.stat().st_size < high.stat().st_size


def test_mtime_is_set_and_existing_copy_is_never_replaced(tmp_path) -> None:
    source = tmp_path / "src.JPG"
    source.write_bytes(image_bytes())
    target = tmp_path / "Compact" / "out.jpg"
    assert make_compact(source, target, mtime=1_700_000_000.0) is True
    assert target.stat().st_mtime == 1_700_000_000.0
    before = target.read_bytes()
    source.write_bytes(image_bytes(color=(0, 0, 255)))
    assert make_compact(source, target) is False
    assert target.read_bytes() == before


def test_unreadable_source_raises_and_leaves_nothing(tmp_path) -> None:
    source = tmp_path / "bad.JPG"
    source.write_bytes(b"not an image")
    with pytest.raises(Exception):
        make_compact(source, tmp_path / "Compact" / "bad.jpg")
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["bad.JPG"]
