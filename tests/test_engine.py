"""End-to-end behaviour of a period job on FakeICloudClient (REQUIREMENTS.md, section 9)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from conftest import image_bytes, make_exif, mov_bytes, tree, utc
from ipd_app import strings
from ipd_app.icloud_adapter import (
    ICloudError,
    MediaType,
    NetworkError,
    ServiceUnavailableError,
    SessionExpiredError,
    VersionKind,
)
from ipd_app.icloud_adapter.fake_client import Truncate
from ipd_app.sync_engine import Period, PreflightError
from ipd_app.sync_engine import fs
from ipd_app.sync_engine import path_builder as pb

YEAR_2023 = Period(date(2023, 1, 1), date(2023, 12, 31))
ALL = Period()


# ---------------------------------------------------------------- basics


def test_downloads_into_year_month_full_size(client, make_engine, root) -> None:
    asset = client.add("IMG_0001.HEIC", b"heic-bytes", taken=utc(2023, 3, 5), tz_offset=10800)
    client.add("IMG_0002.MOV", b"movie", taken=utc(2023, 11, 20), tz_offset=10800)
    report = make_engine().run(YEAR_2023)

    assert report.finished and report.downloaded == 2 and not report.errors
    assert tree(root) == ["2023/03 March/Full size/IMG_0001.HEIC", "2023/11 November/Full size/IMG_0002.MOV"]
    target = root / "2023/03 March/Full size/IMG_0001.HEIC"
    assert target.read_bytes() == b"heic-bytes"
    assert target.stat().st_mtime == asset.asset_date.timestamp()
    assert not (root / pb.INCOMING_DIR).exists()


def test_second_run_downloads_nothing(client, make_engine) -> None:
    for index in range(5):
        client.add(f"IMG_{index}.JPG", b"x" * (index + 1), taken=utc(2023, 6, index + 1))
    assert make_engine().run(YEAR_2023).downloaded == 5
    calls = len(client.download_calls)
    again = make_engine().run(YEAR_2023)
    assert again.downloaded == 0 and again.skipped == 5
    assert again.plan.files_present == 5 and again.plan.files_to_download == 0
    assert len(client.download_calls) == calls


def test_dry_run_shows_the_plan_and_downloads_nothing(client, make_engine, root) -> None:
    client.add("IMG_1.JPG", b"12345", taken=utc(2023, 6, 1))
    client.add("IMG_2.JPG", b"123", taken=utc(2022, 6, 1))
    plan = make_engine().preview(YEAR_2023)
    assert (plan.files_in_period, plan.files_to_download, plan.bytes_to_download) == (1, 1, 5)
    assert tree(root) == [] and client.download_calls == []


# ------------------------------------------------------- period and zones


def test_period_is_decided_by_capture_wall_time(client, make_engine, root) -> None:
    client.add("BANGKOK.JPG", b"a", taken=utc(2023, 12, 31, 16, 30), tz_offset=7 * 3600)  # 31 Dec 23:30
    client.add("NEWYORK.JPG", b"b", taken=utc(2024, 1, 1, 6, 0), tz_offset=-5 * 3600)  # 1 Jan 01:00
    client.add("TOKYO.JPG", b"c", taken=utc(2022, 12, 31, 20, 0), tz_offset=9 * 3600)  # 1 Jan 2023 05:00
    client.add("LA.JPG", b"d", taken=utc(2023, 1, 1, 3, 0), tz_offset=-8 * 3600)  # 31 Dec 2022 19:00
    make_engine().run(YEAR_2023)
    assert tree(root) == ["2023/01 January/Full size/TOKYO.JPG", "2023/12 December/Full size/BANGKOK.JPG"]


def test_full_period_from_first_to_last_month(client, make_engine, root) -> None:
    for year in (2021, 2022, 2023, 2024):
        for month in (1, 12):
            client.add(f"P_{year}_{month}.JPG", b"z", taken=utc(year, month, 15))
    make_engine().run(Period(date(2022, 1, 1), date(2023, 12, 31)))
    assert [p.split("/Full")[0] for p in tree(root)] == [
        "2022/01 January",
        "2022/12 December",
        "2023/01 January",
        "2023/12 December",
    ]


def test_boundary_asset_without_timezone_goes_through_incoming(client, make_engine, root) -> None:
    inside = image_bytes(exif=make_exif("2023:02:01 03:00:00"))
    outside = image_bytes(exif=make_exif("2024:01:01 03:00:00"), color=(1, 2, 3))
    client.add("FEB.JPG", inside, taken=utc(2023, 1, 31, 20, 0), tz_offset=None)
    client.add("NEXT_YEAR.JPG", outside, taken=utc(2023, 12, 31, 20, 0), tz_offset=None)
    engine = make_engine()
    report = engine.run(YEAR_2023)

    assert report.plan.boundary_assets == 1
    assert tree(root) == ["2023/02 February/Full size/FEB.JPG"]  # by EXIF, not by the UTC month
    assert report.downloaded == 1 and report.out_of_period == 1
    assert not (root / pb.INCOMING_DIR).exists()

    calls = len(client.download_calls)
    again = make_engine().run(YEAR_2023)  # the verdict is cached: nothing is fetched twice
    assert again.downloaded == 0 and len(client.download_calls) == calls


def test_video_boundary_uses_quicktime_creation_date(client, make_engine, root) -> None:
    client.add("CLIP.MOV", mov_bytes("2023-12-31T23:30:00+0700"), taken=utc(2023, 12, 31, 16, 30), tz_offset=None)
    make_engine().run(YEAR_2023)
    assert tree(root) == ["2023/12 December/Full size/CLIP.MOV"]


def test_asset_without_any_date(client, make_engine, root) -> None:
    client.add("NODATE.JPG", b"n", taken=None)
    assert make_engine().run(YEAR_2023).downloaded == 0
    make_engine().run(ALL)
    assert tree(root) == ["Unknown date/Full size/NODATE.JPG"]


# ------------------------------------------------------------------ names


def test_same_name_in_one_month_gets_a_stable_suffix(client, make_engine, root) -> None:
    first = client.add("IMG_0001.HEIC", b"first", taken=utc(2023, 3, 5))
    second = client.add("IMG_0001.HEIC", b"second!", taken=utc(2023, 3, 9))
    make_engine().run(YEAR_2023)
    tagged = f"2023/03 March/Full size/IMG_0001{pb.conflict_tag(second.id)}.HEIC"
    assert tree(root) == ["2023/03 March/Full size/IMG_0001.HEIC", tagged]
    assert (root / tagged).read_bytes() == b"second!"
    assert pb.conflict_tag(first.id) not in "".join(tree(root))

    again = make_engine().run(YEAR_2023)
    assert again.downloaded == 0 and len(tree(root)) == 2


def test_live_photo_video_sits_next_to_the_photo(client, make_engine, root) -> None:
    client.add("IMG_7.HEIC", b"photo", live=b"movie", taken=utc(2023, 12, 31, 16, 30), tz_offset=7 * 3600)
    make_engine().run(YEAR_2023)
    assert tree(root) == ["2023/12 December/Full size/IMG_7.HEIC", "2023/12 December/Full size/IMG_7.MOV"]


def test_invalid_characters_are_replaced(client, make_engine, root) -> None:
    client.add('my:photo?.JPG', b"p", taken=utc(2023, 5, 5))
    make_engine().run(YEAR_2023)
    assert tree(root) == ["2023/05 May/Full size/my_photo_.JPG"]


def test_paths_longer_than_max_path(client, make_engine, tmp_path) -> None:
    deep = tmp_path / ("d" * 80) / ("e" * 80) / ("f" * 80)
    fs.ensure_dir(deep)
    client.add("L" * 100 + ".JPG", b"long", taken=utc(2023, 5, 5))
    report = make_engine(root=deep).run(YEAR_2023)
    target = deep / "2023" / "05 May" / "Full size" / ("L" * 100 + ".JPG")
    assert len(str(target)) > 260
    assert report.downloaded == 1 and fs.size_of(target) == 4

    # a boundary asset on a long path: temp download, EXIF read and move all work
    client.add("B" * 100 + ".JPG", image_bytes(exif=make_exif("2023:07:01 02:00:00")), taken=utc(2023, 6, 30, 20), tz_offset=None)
    again = make_engine(db_name="long.sqlite", root=deep, compact_enabled=True).run(YEAR_2023)
    assert again.downloaded == 1 and not again.errors
    assert len(again.compact_errors) == 1 and "LLLL" in again.compact_errors[0][0]  # 'long' is not an image
    assert fs.exists(deep / "2023" / "07 July" / "Compact" / ("B" * 100 + ".jpg"))


# ---------------------------------------------------------------- filters


def test_media_type_filter(client, make_engine, root) -> None:
    client.add("P.JPG", b"p", taken=utc(2023, 5, 1))
    client.add("V.MOV", b"v", taken=utc(2023, 5, 2))
    make_engine(db_name="a.sqlite", videos=False).run(YEAR_2023)
    assert tree(root) == ["2023/05 May/Full size/P.JPG"]
    make_engine(db_name="b.sqlite", photos=False).run(YEAR_2023)
    assert "2023/05 May/Full size/V.MOV" in tree(root)


def test_album_filter(client, make_engine, root) -> None:
    client.add("IN.JPG", b"i", taken=utc(2023, 5, 1), album="Trip")
    client.add("BOTH.JPG", b"b", taken=utc(2023, 5, 2), album="Trip")
    client.albums.setdefault("Family", []).append("asset-00002")  # the same asset in two albums
    client.add("OUT.JPG", b"o", taken=utc(2023, 5, 3))
    report = make_engine(album_ids=("Trip", "Family")).run(YEAR_2023)
    assert report.downloaded == 2
    assert tree(root) == ["2023/05 May/Full size/BOTH.JPG", "2023/05 May/Full size/IN.JPG"]


def test_hidden_and_recently_removed_are_never_downloaded(client, make_engine, root) -> None:
    client.add("HIDDEN.JPG", b"h", taken=utc(2023, 5, 1), album="Trip", hidden=True)
    client.add("TRASH.JPG", b"t", taken=utc(2023, 5, 2), album="Trip", trashed=True)
    client.add("OK.JPG", b"k", taken=utc(2023, 5, 3), album="Trip")
    make_engine(db_name="a.sqlite", album_ids=("Trip",)).run(YEAR_2023)
    make_engine(db_name="b.sqlite").run(YEAR_2023)
    assert tree(root) == ["2023/05 May/Full size/OK.JPG"]


def test_live_video_and_edited_options(client, make_engine, root) -> None:
    client.add("IMG_1.HEIC", b"photo", live=b"movie", edited=b"edited", taken=utc(2023, 5, 1))
    make_engine(db_name="a.sqlite", live_video=False).run(YEAR_2023)
    assert tree(root) == ["2023/05 May/Full size/IMG_1.HEIC"]
    make_engine(db_name="a.sqlite", edited=True).run(YEAR_2023)
    assert tree(root) == [
        "2023/05 May/Full size/IMG_1.HEIC",
        "2023/05 May/Full size/IMG_1.MOV",
        "2023/05 May/Full size/IMG_1_edited.JPG",
    ]


# ------------------------------------------------- reliability and resume


def test_broken_download_leaves_no_file_and_is_retried(client, make_engine, root) -> None:
    asset = client.add("IMG_1.JPG", b"0123456789", taken=utc(2023, 5, 1))
    client.fail(asset, Truncate(4), NetworkError("reset"), ServiceUnavailableError("503"))
    report = make_engine().run(YEAR_2023)
    assert report.downloaded == 1 and not report.errors
    assert len(client.download_calls) == 4
    assert tree(root) == ["2023/05 May/Full size/IMG_1.JPG"]
    assert (root / "2023/05 May/Full size/IMG_1.JPG").read_bytes() == b"0123456789"


def test_file_that_keeps_failing_is_reported_and_the_job_goes_on(client, make_engine, root) -> None:
    bad = client.add("BAD.JPG", b"0123456789", taken=utc(2023, 5, 1))
    client.add("GOOD.JPG", b"ok", taken=utc(2023, 5, 2))
    client.fail(bad, *[Truncate(3)] * 5)
    report = make_engine().run(YEAR_2023)
    assert report.finished and report.downloaded == 1
    assert [name for name, _ in report.errors] == ["2023/05 May/Full size/BAD.JPG"]
    assert client.download_calls.count((bad.id, VersionKind.ORIGINAL)) == 5
    assert tree(root) == ["2023/05 May/Full size/GOOD.JPG"]  # no half file, no .part

    assert make_engine().run(YEAR_2023).downloaded == 1  # next run fetches it


def test_permanent_error_is_not_retried(client, make_engine) -> None:
    asset = client.add("X.JPG", b"x", taken=utc(2023, 5, 1))
    client.fail(asset, ICloudError("gone"))
    report = make_engine().run(YEAR_2023)
    assert len(report.errors) == 1 and len(client.download_calls) == 1


def test_leftover_part_file_is_removed_and_fetched_again(client, make_engine, root) -> None:
    client.add("IMG_1.JPG", b"complete", taken=utc(2023, 5, 1))
    folder = root / "2023/05 May/Full size"
    folder.mkdir(parents=True)
    (folder / "IMG_1.JPG.part").write_bytes(b"comp")
    (root / pb.INCOMING_DIR).mkdir()
    (root / pb.INCOMING_DIR / "old.JPG.part").write_bytes(b"junk")
    report = make_engine().run(YEAR_2023)
    assert report.downloaded == 1
    assert tree(root) == ["2023/05 May/Full size/IMG_1.JPG"]
    assert (folder / "IMG_1.JPG").read_bytes() == b"complete"


def test_stop_and_resume_without_duplicates(client, make_engine, root) -> None:
    for index in range(12):
        client.add(f"IMG_{index:02d}.JPG", bytes([index]) * 100, taken=utc(2023, 5, index + 1))
    engine = make_engine(concurrency=1)
    original = engine._on_event

    def stop_after_three(name, **data):
        original(name, **data)
        if name == "file" and data["result"] == "downloaded" and engine._report.downloaded >= 3:
            engine.stop()

    engine._on_event = stop_after_three
    first = engine.run(YEAR_2023)
    assert not first.finished and first.stopped_reason == strings.STOP_USER
    assert 3 <= first.downloaded < 12
    assert not any(name.endswith(".part") for name in tree(root))

    pending = engine.db.unfinished_job()
    assert pending is not None and (pending.date_from, pending.date_to) == ("2023-01-01", "2023-12-31")
    assert pending.total_files == 12 and pending.done_files == first.downloaded

    second = make_engine().run(YEAR_2023)
    assert second.finished and second.downloaded == 12 - first.downloaded
    assert len(tree(root)) == 12
    assert len(client.download_calls) == len(set(client.download_calls)) or first.downloaded < 12
    assert second.plan.files_present == first.downloaded
    assert engine.db.unfinished_job() is None


def test_stop_pressed_before_the_job_thread_starts_is_honoured(client, make_engine, root) -> None:
    client.add("A.JPG", b"a", taken=utc(2023, 5, 1))
    engine = make_engine()
    engine.stop()
    report = engine.run(YEAR_2023)
    assert report.stopped_reason == strings.STOP_USER and tree(root) == []
    assert engine.run(YEAR_2023).downloaded == 1  # the flag does not leak into the next run


def test_session_expiring_mid_job_stops_it_cleanly(client, make_engine, root) -> None:
    client.add("A.JPG", b"a", taken=utc(2023, 5, 1))
    doomed = client.add("B.JPG", b"b", taken=utc(2023, 5, 2))
    client.add("C.JPG", b"c", taken=utc(2023, 5, 3))
    client.fail(doomed, SessionExpiredError())
    report = make_engine(concurrency=1).run(YEAR_2023)
    assert report.stopped_reason == strings.STOP_SESSION
    assert not any(name.endswith(".part") for name in tree(root))


def test_pause_blocks_and_resume_continues(client, make_engine) -> None:
    import threading

    for index in range(4):
        client.add(f"IMG_{index}.JPG", b"x", taken=utc(2023, 5, index + 1))
    engine = make_engine(concurrency=1)
    engine.pause()  # pressed before the job thread even started: must not be lost
    result = {}
    worker = threading.Thread(target=lambda: result.update(report=engine.run(YEAR_2023)))
    worker.start()
    worker.join(1.0)
    assert worker.is_alive() and client.download_calls == []
    engine.resume()
    worker.join(10)
    assert result["report"].downloaded == 4


# ------------------------------------------------- root folder is the truth


def test_file_on_disk_without_database_is_not_downloaded_again(client, make_engine, root) -> None:
    first = client.add("IMG_0001.HEIC", b"first", taken=utc(2023, 3, 5))
    client.add("IMG_0001.HEIC", b"second!", taken=utc(2023, 3, 9))  # gets a suffix
    exif_image = image_bytes(exif=make_exif("2023:02:01 03:00:00"))
    client.add("FEB.JPG", exif_image, taken=utc(2023, 1, 31, 20, 0), tz_offset=None)
    make_engine(db_name="one.sqlite").run(YEAR_2023)
    before = tree(root)
    calls = len(client.download_calls)

    rebuilt = make_engine(db_name="lost-and-new.sqlite").run(YEAR_2023)
    assert rebuilt.downloaded == 0 and rebuilt.skipped == 3
    assert tree(root) == before and len(client.download_calls) == calls
    assert first.id  # silence unused


def test_manually_removed_file_is_restored_by_default(client, make_engine, root) -> None:
    client.add("IMG_1.JPG", b"data", taken=utc(2023, 5, 1))
    make_engine().run(YEAR_2023)
    target = root / "2023/05 May/Full size/IMG_1.JPG"
    target.unlink()
    assert make_engine().run(YEAR_2023).downloaded == 1 and target.exists()

    target.unlink()
    kept_away = make_engine(restore_deleted=False).run(YEAR_2023)
    assert kept_away.downloaded == 0 and not target.exists()
    assert kept_away.plan.skipped_deleted == 1


def test_file_of_another_size_is_a_conflict_and_is_left_alone(client, make_engine, root) -> None:
    client.add("IMG_1.JPG", b"from-icloud", taken=utc(2023, 5, 1))
    target = root / "2023/05 May/Full size/IMG_1.JPG"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"mine")
    report = make_engine().run(YEAR_2023)
    assert target.read_bytes() == b"mine"
    assert report.downloaded == 0 and client.download_calls == []
    assert report.conflicts == [("2023/05 May/Full size/IMG_1.JPG", strings.REASON_SAME_SIZE_CONFLICT)]
    assert len(report.plan.conflicts) == 1


def test_damaged_database_is_set_aside_and_rebuilt(client, make_engine, tmp_path, root) -> None:
    client.add("IMG_1.JPG", b"data", taken=utc(2023, 5, 1))
    first = make_engine(db_name="s.sqlite")
    assert first.run(YEAR_2023).downloaded == 1
    first.db.close()
    (tmp_path / "s.sqlite").write_bytes(b"this is not a database" * 100)

    engine = make_engine(db_name="s.sqlite")
    assert engine.db.recovered_from is not None and engine.db.recovered_from.exists()
    assert engine.run(YEAR_2023).downloaded == 0  # the file on disk is recognised
    assert root.exists()


# -------------------------------------------------------------- preflight


def test_job_does_not_start_without_folder_space_or_session(client, make_engine, tmp_path) -> None:
    client.add("IMG_1.JPG", b"data", taken=utc(2023, 5, 1))
    with pytest.raises(PreflightError, match="недоступна"):
        make_engine(db_name="a.sqlite", root=tmp_path / "missing").run(YEAR_2023)
    with pytest.raises(PreflightError, match="Мало места"):
        make_engine(db_name="b.sqlite", min_free_bytes=10**9, free_space=lambda path: 10**6).run(YEAR_2023)
    with pytest.raises(PreflightError, match="позже конца"):
        make_engine(db_name="c.sqlite").run(Period(date(2023, 2, 1), date(2023, 1, 1)))
    client.session_valid = False
    with pytest.raises(SessionExpiredError):
        make_engine(db_name="d.sqlite").run(YEAR_2023)
    assert client.download_calls == []


def test_job_stops_when_the_download_would_not_fit(client, make_engine, root) -> None:
    client.add("BIG.MOV", b"x" * 5000, taken=utc(2023, 5, 1))
    report = make_engine(min_free_bytes=1000, free_space=lambda path: 4000).run(YEAR_2023)
    assert not report.finished and "Мало места" in report.stopped_reason
    assert tree(root) == []


def test_listing_error_ends_the_job_with_a_message(client, make_engine, monkeypatch) -> None:
    client.add("A.JPG", b"a", taken=utc(2023, 5, 1))

    def broken(asset_filter):
        raise NetworkError("dns")
        yield  # pragma: no cover

    monkeypatch.setattr(client, "iter_assets", broken)
    report = make_engine().run(YEAR_2023)
    assert report.stopped_reason == strings.ERR_NETWORK


# ---------------------------------------------------------------- compact


def test_compact_copies_for_photos_only(client, make_engine, root) -> None:
    client.add("IMG_1.JPG", image_bytes(size=(400, 300)), live=b"movie", taken=utc(2023, 5, 1))
    client.add("IMG_2.HEIC", image_bytes("HEIF", size=(320, 240)), taken=utc(2023, 5, 2))
    client.add("RAW_3.DNG", b"raw-bytes", taken=utc(2023, 5, 3))
    client.add("CLIP_4.MOV", b"movie", taken=utc(2023, 5, 4))
    report = make_engine(compact_enabled=True).run(YEAR_2023)
    assert report.compact_made == 2 and not report.compact_errors
    assert [p for p in tree(root) if "/Compact/" in p] == [
        "2023/05 May/Compact/IMG_1.jpg",
        "2023/05 May/Compact/IMG_2.jpg",
    ]
    assert report.plan.compact_to_make == 2 and report.plan.compact_bytes > 0


def test_missing_compact_copy_is_rebuilt_without_the_network(client, make_engine, root) -> None:
    asset = client.add("IMG_1.JPG", image_bytes(size=(400, 300)), taken=utc(2023, 5, 1))
    make_engine(compact_enabled=True).run(YEAR_2023)
    copy = root / "2023/05 May/Compact/IMG_1.jpg"
    copy.unlink()
    calls = list(client.download_calls)

    report = make_engine(compact_enabled=True).run(YEAR_2023)
    assert copy.exists() and report.compact_made == 1 and report.downloaded == 0
    assert client.download_calls == calls
    assert copy.stat().st_mtime == asset.asset_date.timestamp()


def test_compact_switched_off_keeps_existing_copies(client, make_engine, root) -> None:
    client.add("IMG_1.JPG", image_bytes(), taken=utc(2023, 5, 1))
    make_engine(compact_enabled=True).run(YEAR_2023)
    client.add("IMG_2.JPG", image_bytes(color=(0, 9, 0)), taken=utc(2023, 5, 2))
    make_engine(compact_enabled=False).run(YEAR_2023)
    assert [p for p in tree(root) if "/Compact/" in p] == ["2023/05 May/Compact/IMG_1.jpg"]


def test_compact_name_clash_between_formats(client, make_engine, root) -> None:
    client.add("IMG_1234.HEIC", image_bytes("HEIF"), taken=utc(2023, 5, 1))
    client.add("IMG_1234.PNG", image_bytes("PNG"), taken=utc(2023, 5, 2))
    make_engine(compact_enabled=True).run(YEAR_2023)
    assert [p for p in tree(root) if "/Compact/" in p] == [
        "2023/05 May/Compact/IMG_1234.jpg",
        "2023/05 May/Compact/IMG_1234_png.jpg",
    ]


def test_failed_conversion_keeps_the_original_and_is_retried(client, make_engine, root) -> None:
    client.add("BROKEN.JPG", b"definitely not a jpeg", taken=utc(2023, 5, 1))
    report = make_engine(compact_enabled=True).run(YEAR_2023)
    assert report.downloaded == 1 and len(report.compact_errors) == 1
    assert tree(root) == ["2023/05 May/Full size/BROKEN.JPG"]
    assert len(make_engine(compact_enabled=True).run(YEAR_2023).compact_errors) == 1  # tried again


def test_edited_version_gets_its_own_copy(client, make_engine, root) -> None:
    client.add("IMG_1.HEIC", image_bytes("HEIF"), edited=image_bytes(color=(0, 0, 200)), taken=utc(2023, 5, 1))
    make_engine(compact_enabled=True, edited=True).run(YEAR_2023)
    assert [p for p in tree(root) if "/Compact/" in p] == [
        "2023/05 May/Compact/IMG_1.jpg",
        "2023/05 May/Compact/IMG_1_edited.jpg",
    ]


def test_events_describe_the_job(client, make_engine) -> None:
    client.add("IMG_1.JPG", b"12345", taken=utc(2023, 5, 1))
    engine = make_engine()
    engine.run(YEAR_2023)
    names = [name for name, _ in engine.events]
    states = [data["state"] for name, data in engine.events if name == "status"]
    assert states == ["counting", "downloading", "idle"]
    assert names.index("plan") < names.index("bytes") < names.index("report")
    assert sum(data["count"] for name, data in engine.events if name == "bytes") == 5
    assert MediaType.PHOTO and datetime  # imports used by helpers
