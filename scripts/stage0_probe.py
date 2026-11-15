"""Stage 0 technology probe (REQUIREMENTS.md, section 11).

Logs in to iCloud with 2FA, lists the 20 most recent assets with their dates,
and downloads 3 original files. Read-only: nothing is changed or removed in
iCloud, and existing local files are never overwritten.

Usage:
    python scripts/stage0_probe.py --apple-id you@example.com

The password is asked interactively and is never stored, printed or logged.
Run it a second time to check that the saved session is reused (no password,
no 2FA code).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

APP_DIR_NAME = "iCloudPhotoDownloader"
LIST_COUNT = 20
DOWNLOAD_COUNT = 3
CHUNK_SIZE = 64 * 1024
# Offsets outside UTC-12..UTC+14 mean the field is not "seconds east of UTC".
MAX_TZ_OFFSET_SECONDS = 14 * 3600


# --------------------------------------------------------------------------
# Pure helpers (covered by tests/test_stage0_probe.py)
# --------------------------------------------------------------------------


def account_id(apple_id: str) -> str:
    """Stable folder-safe id for an Apple ID (no e-mail on disk)."""
    return hashlib.sha256(apple_id.strip().lower().encode("utf-8")).hexdigest()[:16]


def mask_apple_id(apple_id: str) -> str:
    """al***@example.com style masking for anything printed or logged."""
    local, sep, domain = apple_id.partition("@")
    if not sep:
        return local[:2] + "***"
    return f"{local[:2]}***@{domain}"


def session_dir(apple_id: str, appdata: str | None = None) -> Path:
    """%APPDATA%\\iCloudPhotoDownloader\\sessions\\<account_id>\\"""
    base = appdata or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_DIR_NAME / "sessions" / account_id(apple_id)


def capture_wall_time(asset_date_ms: Any, tz_offset_seconds: Any) -> datetime | None:
    """Wall-clock time on the phone at the moment of capture, as a naive datetime.

    Returns None when either value is missing or the offset is implausible, so
    the caller can fall back to the next source from REQUIREMENTS 6.3.
    """
    if isinstance(asset_date_ms, bool) or not isinstance(asset_date_ms, (int, float)):
        return None
    if isinstance(tz_offset_seconds, bool) or not isinstance(tz_offset_seconds, (int, float)):
        return None
    if abs(tz_offset_seconds) > MAX_TZ_OFFSET_SECONDS:
        return None
    utc = datetime.fromtimestamp(asset_date_ms / 1000.0, tz=timezone.utc)
    return (utc + timedelta(seconds=tz_offset_seconds)).replace(tzinfo=None)


def field_value(record: dict[str, Any], name: str) -> Any:
    """Value of a CloudKit record field, or None when the field is absent."""
    field = record.get("fields", {}).get(name)
    return field.get("value") if isinstance(field, dict) else None


def classify_error(error: BaseException) -> str:
    """Russian, user-facing message for a login / library error."""
    text = str(error)
    name = type(error).__name__
    if "Web access to iCloud data is disabled" in text:
        return "Веб-доступ к iCloud выключен. Включите «Доступ к данным iCloud через веб» на iPhone."
    if "Timed out waiting for the iCloud web access approval" in text:
        return "Запрос веб-доступа не подтверждён на устройстве Apple (Advanced Data Protection)."
    if "Invalid email/password" in text or "Failed to initiate srp" in text:
        return "Неверный Apple ID или пароль."
    if name == "PyiCloudFailedMFAException":
        return "Код 2FA не принят."
    if name == "PyiCloudServiceNotActivatedException":
        return (
            "Медиатека iCloud недоступна. Возможные причины: включена Advanced Data "
            "Protection, выключен веб-доступ к iCloud или медиатека ещё индексируется."
        )
    if name == "PyiCloudConnectionErrorException":
        return "Нет связи с серверами iCloud."
    if name == "PyiCloudServiceUnavailableException":
        return "Сервис iCloud временно недоступен (503). Повторите позже."
    if "Authentication required" in text or "Invalid global session" in text:
        return "Сессия истекла, войдите заново."
    if "ACCESS_DENIED" in text:
        return (
            "iCloud отказал в доступе к фото. Возможно, включена Advanced Data Protection "
            "(запустите с --adp) или Apple временно ограничил запросы."
        )
    return f"Ошибка iCloud: {name}: {text}"


# --------------------------------------------------------------------------
# iCloud steps
# --------------------------------------------------------------------------


def read_masked(getch: Any, write: Any, clipboard: Any) -> str:
    """Read a secret key by key, echoing '*' so the user can see that typing works.

    Ctrl+V pastes the clipboard: in a raw console read it arrives as the control
    character 0x16 and would otherwise silently become the "password".
    """
    chars: list[str] = []
    while True:
        key = getch()
        if key in ("\r", "\n"):
            write("\n")
            return "".join(chars)
        if key == "\x03":
            raise KeyboardInterrupt
        if key in ("\x00", "\xe0"):  # arrows, F-keys: two-part codes, skip both parts
            getch()
        elif key == "\b":
            if chars:
                chars.pop()
                write("\b \b")
        elif key == "\x16":
            pasted = [c for c in clipboard() if c >= " "]
            chars.extend(pasted)
            write("*" * len(pasted))
        elif key >= " ":
            chars.append(key)
            write("*")


def clipboard_text() -> str:
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        try:
            return str(root.clipboard_get())
        finally:
            root.destroy()
    except Exception:  # noqa: BLE001 - empty or non-text clipboard, no display
        return ""


def ask_password(prompt: str) -> str:
    try:
        import msvcrt
    except ImportError:
        return getpass.getpass(prompt)
    if not sys.stdin.isatty():
        return getpass.getpass(prompt)

    def write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    write(prompt)
    return read_masked(msvcrt.getwch, write, clipboard_text)


@dataclass
class LoginState:
    password_was_asked: bool = False
    code_was_asked: bool = False


def login(apple_id: str, cookie_dir: Path, domain: str, state: LoginState) -> Any:
    from pyicloud_ipd.base import PyiCloudService

    def password_provider() -> str:
        # Called by the library only when the saved session is missing or expired.
        state.password_was_asked = True
        print("Символы пароля показываются звёздочками. Вставка: Ctrl+V или правая кнопка мыши.")
        return ask_password(f"Пароль для {mask_apple_id(apple_id)}: ")

    cookie_dir.mkdir(parents=True, exist_ok=True)
    return PyiCloudService(domain, apple_id, password_provider, cookie_directory=str(cookie_dir))


def ask_code(prompt: str) -> str:
    while True:
        code = input(prompt).strip()
        if len(code) == 6 and code.isdigit():
            return code
        print("Нужно 6 цифр.")


def complete_2fa(icloud: Any, state: LoginState) -> None:
    from pyicloud_ipd.exceptions import PyiCloudFailedMFAException

    state.code_was_asked = True
    phones = list(icloud.get_trusted_phone_numbers())
    if not phones and icloud.get_security_key_challenge():
        raise PyiCloudFailedMFAException("Security keys (FIDO) are not supported by this probe")

    pushed = icloud.trigger_push_notification()
    print(f"Запрошен код на доверенные устройства: {'да' if pushed else 'не удалось'}")

    letters = "abcdefghijklmnopqrstuvwxyz"
    for letter, phone in zip(letters, phones):
        print(f"  {letter}: SMS на {phone.obfuscated_number}")
    hint = " или букву номера для SMS" if phones else ""
    while True:
        answer = input(f"Код 2FA (6 цифр){hint}: ").strip().lower()
        if len(answer) == 6 and answer.isdigit():
            ok = icloud.validate_2fa_code(answer)
            break
        if len(answer) == 1 and answer in letters[: len(phones)]:
            phone = phones[letters.index(answer)]
            if not icloud.send_2fa_code_sms(phone.id):
                raise PyiCloudFailedMFAException("Failed to send SMS code")
            ok = icloud.validate_2fa_code_sms(phone.id, ask_code("Код из SMS: "))
            break
        print("Не понял ввод.")
    if not ok:
        raise PyiCloudFailedMFAException("Failed to verify two-factor authentication code")


def recent_assets(album: Any, count: int) -> tuple[int, list[Any]]:
    """Last `count` assets of an album ordered by asset date (oldest first)."""
    total = len(album)
    # The library can only walk in ascending rank order; start near the end.
    album.offset = max(0, total - count)
    return total, list(album)[-count:]


def describe(asset: Any) -> dict[str, Any]:
    record = asset._asset_record  # noqa: SLF001 - the library does not expose timeZoneOffset
    date_ms = field_value(record, "assetDate")
    tz_raw = field_value(record, "timeZoneOffset")
    versions = asset.versions
    return {
        "filename": asset.filename,
        "type": asset.item_type.name if asset.item_type else "?",
        "asset_date_utc": asset.asset_date if asset.has_asset_date else None,
        "added_date_utc": asset.added_date,
        "tz_offset_raw": tz_raw,
        "capture_wall_time": capture_wall_time(date_ms, tz_raw),
        "versions": sorted(f"{type(k).__name__[0]}:{k.name}" for k in versions),
    }


def fmt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else "-"


def download_original(icloud: Any, asset: Any, out_dir: Path) -> str:
    from pyicloud_ipd.version_size import AssetVersionSize

    version = asset.versions.get(AssetVersionSize.ORIGINAL)
    if version is None:
        return "нет версии ORIGINAL"
    target = out_dir / asset.filename
    if target.exists():
        same = target.stat().st_size == version.size
        return "уже есть, размер совпадает" if same else "уже есть с другим размером, не трогаю"

    part = target.with_name(target.name + ".part")
    started = time.monotonic()
    response = asset.download(icloud.photos.session, version.url)
    if not response.ok:
        return f"HTTP {response.status_code}"
    with open(part, "wb") as handle:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                handle.write(chunk)
    got = part.stat().st_size
    if got != version.size:
        return f"размер не сошёлся: {got} из {version.size} (оставлен {part.name})"
    os.replace(part, target)
    if asset.has_asset_date:
        stamp = asset.asset_date.timestamp()
        os.utime(target, (stamp, stamp))
    seconds = max(time.monotonic() - started, 0.001)
    return f"OK, {got / 1_048_576:.1f} МБ за {seconds:.1f} с"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 0 probe: iCloud login, listing, download")
    parser.add_argument("--apple-id", required=True, help="Apple ID (e-mail)")
    parser.add_argument("--domain", choices=["com", "cn"], default="com")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "_stage0_downloads",
        help="folder for the 3 test downloads (default: _stage0_downloads in the repo)",
    )
    parser.add_argument(
        "--cookie-dir", type=Path, default=None, help="session folder (default: %%APPDATA%%)"
    )
    parser.add_argument(
        "--adp",
        action="store_true",
        help="account has Advanced Data Protection: request web access consent on a device",
    )
    parser.add_argument("--no-download", action="store_true", help="only log in and list assets")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    cookie_dir = args.cookie_dir or session_dir(args.apple_id)
    state = LoginState()
    print(f"Аккаунт: {mask_apple_id(args.apple_id)}")
    print(f"Папка сессии: {cookie_dir}")

    icloud = login(args.apple_id, cookie_dir, args.domain, state)
    if icloud.requires_2fa:
        complete_2fa(icloud, state)
    elif icloud.requires_2sa:
        print("Аккаунт использует устаревшую двухэтапную проверку (2SA). Проба её не поддерживает.")
        return 2
    if args.adp:
        print("Подтвердите запрос веб-доступа на устройстве Apple (до 2 минут)...")
        icloud.request_pcs_consent("photos")

    ds_info = icloud.data.get("dsInfo", {})
    print("\n[1] Вход выполнен")
    print(f"    пароль запрашивался: {'да' if state.password_was_asked else 'нет (сессия с диска)'}")
    print(f"    код 2FA запрашивался: {'да' if state.code_was_asked else 'нет'}")
    print(f"    hsaVersion={ds_info.get('hsaVersion')} trusted={icloud.is_trusted_session}")
    for key in ("iCDPEnabled", "isWebAccessAllowed", "pcsEnabled"):
        if key in icloud.data or key in ds_info:
            print(f"    {key}={icloud.data.get(key, ds_info.get(key))}")
    print(f"    файлы сессии: {sorted(p.name for p in cookie_dir.iterdir())}")

    total, assets = recent_assets(icloud.photos.all, LIST_COUNT)
    print(f"\n[2] Всего в медиатеке: {total}. Последние {len(assets)} по дате съёмки:")
    header = (
        f"    {'файл':<28}{'тип':<7}{'съёмка UTC':<21}{'tz, raw':<10}"
        f"{'время на телефоне':<21}{'добавлено UTC':<21}версии"
    )
    print(header)
    for asset in assets:
        row = describe(asset)
        print(
            f"    {row['filename'][:27]:<28}{row['type']:<7}{fmt(row['asset_date_utc']):<21}"
            f"{row['tz_offset_raw']!s:<10}{fmt(row['capture_wall_time']):<21}"
            f"{fmt(row['added_date_utc']):<21}{' '.join(row['versions'])}"
        )
    if assets:
        record = assets[-1]._asset_record  # noqa: SLF001
        print(f"\n    поля CPLAsset: {sorted(record.get('fields', {}))}")
        with_tz = sum(1 for a in assets if describe(a)["tz_offset_raw"] is not None)
        print(f"    timeZoneOffset заполнен у {with_tz} из {len(assets)}")

    if args.no_download:
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"\n[3] Загрузка {DOWNLOAD_COUNT} оригиналов в {args.out}")
    failed = 0
    for asset in assets[-DOWNLOAD_COUNT:]:
        result = download_original(icloud, asset, args.out)
        failed += 0 if result.startswith(("OK", "уже есть, размер совпадает")) else 1
        print(f"    {asset.filename}: {result}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nПрервано.")
        return 130
    except Exception as error:  # noqa: BLE001 - the probe must end with a readable message
        print(f"\nОШИБКА: {classify_error(error)}")
        print(f"(техническая причина: {type(error).__name__}: {error})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
