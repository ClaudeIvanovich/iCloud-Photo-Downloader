from __future__ import annotations

import locale
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePosixPath

import pytest

from conftest import MOSCOW, image_bytes, make_exif, mov_bytes, utc
from ipd_app.icloud_adapter import Asset, AssetVersion, MediaType, VersionKind
from ipd_app.sync_engine import capture as cap
from ipd_app.sync_engine import path_builder as pb
from ipd_app.sync_engine.capture import Period


def asset(name="IMG_0001.HEIC", taken=None, tz=None, added=None, media=MediaType.PHOTO, asset_id="A1", live=False, edited=None):
    versions = {VersionKind.ORIGINAL: AssetVersion(VersionKind.ORIGINAL, 10, name[name.rfind(".") :])}
    if live:
        versions[VersionKind.LIVE_VIDEO] = AssetVersion(VersionKind.LIVE_VIDEO, 5, ".MOV")
    if edited:
        versions[VersionKind.EDITED] = AssetVersion(VersionKind.EDITED, 7, edited)
    return Asset(asset_id, name, media, taken, added, tz, versions)


# ----------------------------------------------------------------- folders


def test_month_folders_are_numbered_english_names() -> None:
    assert [pb.month_folder(m) for m in (1, 2, 3, 12)] == ["01 January", "02 February", "03 March", "12 December"]
    assert pb.month_dir(datetime(2023, 3, 5)) == PurePosixPath("2023/03 March")
    assert pb.month_dir(None) == PurePosixPath("Unknown date")


def test_month_names_ignore_russian_locale() -> None:
    saved = locale.setlocale(locale.LC_TIME)
    try:
        try:
            locale.setlocale(locale.LC_TIME, "Russian_Russia")
        except locale.Error:
            pytest.skip("Russian locale is not installed")
        assert datetime(2023, 3, 5).strftime("%B") != "March"  # the trap we avoid
        assert pb.month_dir(datetime(2023, 3, 5)) == PurePosixPath("2023/03 March")
    finally:
        locale.setlocale(locale.LC_TIME, saved)


# ------------------------------------------------------------ capture time


def wall(a: Asset, period: Period = Period()) -> datetime | None:
    resolution = cap.resolve(a, period, None, MOSCOW)
    assert resolution.capture is not None
    return resolution.capture.wall


def test_bangkok_before_midnight_stays_in_december() -> None:
    assert wall(asset(taken=utc(2023, 12, 31, 16, 30), tz=7 * 3600)) == datetime(2023, 12, 31, 23, 30)


def test_new_york_after_midnight_is_january() -> None:
    assert wall(asset(taken=utc(2024, 1, 1, 6, 0), tz=-5 * 3600)) == datetime(2024, 1, 1, 1, 0)


def test_capture_time_does_not_depend_on_computer_timezone() -> None:
    a = asset(taken=utc(2023, 3, 31, 21, 30), tz=9 * 3600)  # Tokyo, already 1 April
    for local in (timezone.utc, MOSCOW, timezone(timedelta(hours=-8))):
        assert cap.resolve(a, Period(), None, local).capture.wall == datetime(2023, 4, 1, 6, 30)


def test_month_end_and_midnight_crossings() -> None:
    assert pb.month_dir(wall(asset(taken=utc(2023, 2, 28, 22, 0), tz=3 * 3600))) == PurePosixPath("2023/03 March")
    assert pb.month_dir(wall(asset(taken=utc(2024, 3, 1, 2, 0), tz=-8 * 3600))) == PurePosixPath("2024/02 February")


def test_no_capture_date_falls_back_to_added_date_then_unknown() -> None:
    resolution = cap.resolve(asset(added=utc(2023, 5, 1, 22, 0)), Period(), None, MOSCOW)
    assert resolution.capture == cap.Capture(datetime(2023, 5, 2, 1, 0), cap.SOURCE_ADDED)
    nothing = cap.resolve(asset(), Period(), None, MOSCOW)
    assert nothing.capture.wall is None and nothing.in_period is True
    assert cap.resolve(asset(), Period(date(2023, 1, 1), None), None, MOSCOW).in_period is False


def test_without_timezone_mid_month_is_decided_without_the_file() -> None:
    resolution = cap.resolve(asset(taken=utc(2023, 3, 15)), Period(date(2023, 1, 1), date(2023, 12, 31)), None, MOSCOW)
    assert resolution.in_period is True and resolution.capture.source == cap.SOURCE_UTC_WINDOW


def test_without_timezone_near_a_boundary_needs_the_file() -> None:
    period = Period(date(2023, 1, 1), date(2023, 12, 31))
    month_edge = cap.resolve(asset(taken=utc(2023, 3, 31, 20, 0)), period, None, MOSCOW)
    assert month_edge.capture is None and month_edge.in_period is True
    period_edge = cap.resolve(asset(taken=utc(2023, 12, 31, 20, 0)), period, None, MOSCOW)
    assert period_edge.capture is None and period_edge.in_period is None
    far_outside = cap.resolve(asset(taken=utc(2024, 2, 1)), period, None, MOSCOW)
    assert far_outside.in_period is False


def test_cached_capture_settles_a_boundary_case() -> None:
    period = Period(date(2023, 1, 1), date(2023, 12, 31))
    cached = cap.Capture(datetime(2024, 1, 1, 3, 0), cap.SOURCE_FILE)
    assert cap.resolve(asset(taken=utc(2023, 12, 31, 20, 0)), period, cached, MOSCOW).in_period is False


def test_period_bounds_are_inclusive_and_window_has_margin() -> None:
    period = Period(date(2022, 1, 1), date(2023, 12, 31))
    assert period.contains(date(2022, 1, 1)) and period.contains(date(2023, 12, 31))
    assert not period.contains(date(2021, 12, 31)) and not period.contains(date(2024, 1, 1))
    start, end = period.utc_window()
    assert start == utc(2021, 12, 31, 10, 0)
    assert end.date() == date(2024, 1, 1) and end.hour == 13


def test_photo_time_is_read_from_exif(tmp_path) -> None:
    path = tmp_path / "a.part"
    path.write_bytes(image_bytes(exif=make_exif("2024:01:01 03:00:05")))
    assert cap.read_photo_wall_time(path) == datetime(2024, 1, 1, 3, 0, 5)
    found = cap.from_file(path, MediaType.PHOTO, asset(taken=utc(2023, 12, 31, 20, 0)), MOSCOW)
    assert found == cap.Capture(datetime(2024, 1, 1, 3, 0, 5), cap.SOURCE_FILE)


def test_video_time_is_read_from_quicktime_creationdate(tmp_path) -> None:
    path = tmp_path / "v.part"
    path.write_bytes(mov_bytes("2023-12-31T23:30:00+0700"))
    assert cap.read_video_wall_time(path) == datetime(2023, 12, 31, 23, 30)
    path.write_bytes(mov_bytes(None))
    assert cap.read_video_wall_time(path) is None


def test_file_without_metadata_uses_the_computer_timezone(tmp_path) -> None:
    path = tmp_path / "plain.part"
    path.write_bytes(image_bytes())
    found = cap.from_file(path, MediaType.PHOTO, asset(taken=utc(2023, 12, 31, 22, 0)), MOSCOW)
    assert found == cap.Capture(datetime(2024, 1, 1, 1, 0), cap.SOURCE_LOCAL_TZ)


# ------------------------------------------------------------------- names


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("IMG_0001.HEIC", "IMG_0001.HEIC"),
        ('a<b>c:d"e/f\\g|h?i*.jpg', "a_b_c_d_e_f_g_h_i_.jpg"),
        ("trailing. .", "trailing"),
        ("CON.jpg", "_CON.jpg"),
        ("\x01bad\x1f.png", "_bad_.png"),
        (".hidden", ".hidden"),
    ],
)
def test_sanitize_filename(raw: str, clean: str) -> None:
    assert pb.sanitize_filename(raw) == clean


def test_long_names_are_shortened_but_keep_the_extension() -> None:
    name = pb.sanitize_filename("x" * 400 + ".HEIC")
    assert len(name) == pb.MAX_NAME_LENGTH and name.endswith(".HEIC")


def test_conflict_tag_is_short_and_deterministic() -> None:
    assert pb.conflict_tag("ABC") == pb.conflict_tag("ABC") != pb.conflict_tag("ABD")
    assert len(pb.conflict_tag("ABC")) == 7


def test_version_names() -> None:
    a = asset("IMG_0001.HEIC", live=True, edited=".JPG")
    tag = pb.conflict_tag(a.id)
    assert pb.version_filename(a, VersionKind.ORIGINAL) == "IMG_0001.HEIC"
    assert pb.version_filename(a, VersionKind.LIVE_VIDEO) == "IMG_0001.MOV"
    assert pb.version_filename(a, VersionKind.EDITED) == "IMG_0001_edited.JPG"
    assert pb.version_filename(a, VersionKind.ORIGINAL, tag) == f"IMG_0001{tag}.HEIC"
    assert pb.version_filename(a, VersionKind.EDITED, tag) == f"IMG_0001{tag}_edited.JPG"


def test_compact_names_and_eligibility() -> None:
    folder = PurePosixPath("2023/03 March")
    assert pb.compact_path(folder, "IMG_1234.HEIC") == folder / "Compact" / "IMG_1234.jpg"
    assert pb.compact_path(folder, "IMG_1234.PNG", True) == folder / "Compact" / "IMG_1234_png.jpg"
    photo = asset("IMG_1.HEIC", live=True)
    assert pb.wants_compact(photo, VersionKind.ORIGINAL, "IMG_1.HEIC")
    assert not pb.wants_compact(photo, VersionKind.LIVE_VIDEO, "IMG_1.MOV")
    assert not pb.wants_compact(asset("IMG_2.DNG"), VersionKind.ORIGINAL, "IMG_2.DNG")
    assert not pb.wants_compact(asset("IMG_3.MOV", media=MediaType.VIDEO), VersionKind.ORIGINAL, "IMG_3.MOV")
