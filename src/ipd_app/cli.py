"""Debug command line for the core (stage 1). The GUI will drive the same engine.

    python -m ipd_app login    --account you@example.com
    python -m ipd_app set-root --account you@example.com D:\\Photos\\Me
    python -m ipd_app albums   --account you@example.com
    python -m ipd_app sync     --account you@example.com --from 2022-01-01 --to 2023-12-31 --dry-run
    python -m ipd_app sync     --fake 40 --root D:\\Temp\\demo --from 2023-11-01 --to 2024-02-29
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from . import __version__, config, strings
from .accounts import PasswordStore
from .icloud_adapter import ICloudClient, ICloudError, LoginStatus
from .logging_setup import install_excepthook, mask_apple_id, secret_filter, setup_logging
from .sync_engine import Period, Plan, PreflightError, Report, StateDB, SyncEngine

log = logging.getLogger("ipd_app.cli")

FAKE_ACCOUNT = "demo@fake.invalid"


# --------------------------------------------------------------------------
# Console input
# --------------------------------------------------------------------------


def read_masked(getch: Callable[[], str], write: Callable[[str], None], clipboard: Callable[[], str]) -> str:
    """Read a secret key by key, echoing '*'. Ctrl+V pastes the clipboard: in a raw
    console read it arrives as 0x16 and would otherwise become the 'password'."""
    chars: list[str] = []
    while True:
        key = getch()
        if key in ("\r", "\n"):
            write("\n")
            return "".join(chars)
        if key == "\x03":
            raise KeyboardInterrupt
        if key in ("\x00", "\xe0"):  # arrows, F-keys: two-part codes
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


def _clipboard_text() -> str:
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        try:
            return str(root.clipboard_get())
        finally:
            root.destroy()
    except Exception:  # noqa: BLE001 - empty clipboard or no display
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
    return read_masked(msvcrt.getwch, write, _clipboard_text)


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------


def make_client(apple_id: str) -> ICloudClient:
    from .icloud_adapter.pyicloud_client import PyiCloudClient

    return PyiCloudClient(config.session_dir(apple_id))


def sign_in(client: ICloudClient, apple_id: str, store: PasswordStore, interactive: bool = True) -> None:
    """Reuse the saved session; otherwise ask for what is missing. Raises ICloudError."""
    result = client.login(apple_id, None)
    if result.status is LoginStatus.OK:
        return
    if not interactive:
        raise result.error or ICloudError("sign-in required")
    password = store.get(apple_id)
    typed = False
    if not password:
        print("Символы пароля показываются звёздочками. Вставка: Ctrl+V или правая кнопка мыши.")
        password = ask_password(f"Пароль для {mask_apple_id(apple_id)}: ")
        secret_filter.add_secret(password)
        typed = True
    result = client.login(apple_id, password)
    if result.status is LoginStatus.NEEDS_2FA:
        letters = "abcdefghij"
        for letter, phone in zip(letters, result.phones):
            print(f"  {letter}: SMS на {phone.masked_number}")
        hint = " или букву номера для SMS" if result.phones else ""
        while True:
            answer = input(f"Код подтверждения (6 цифр){hint}: ").strip().lower()
            if len(answer) == 6 and answer.isdigit():
                secret_filter.add_secret(answer)
                result = client.submit_2fa_code(answer)
                break
            if len(answer) == 1 and answer in letters[: len(result.phones)]:
                phone = result.phones[letters.index(answer)]
                client.request_sms_code(phone.id)
                code = input("Код из SMS: ").strip()
                secret_filter.add_secret(code)
                result = client.submit_sms_code(phone.id, code)
                break
            print("Нужно 6 цифр.")
    if result.status is not LoginStatus.OK:
        raise result.error or ICloudError("sign-in failed")
    if typed:
        store.save(apple_id, password)


def parse_day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def print_plan(plan: Plan) -> None:
    print(
        strings.PLAN_SUMMARY.format(
            total=plan.files_in_period,
            present=plan.files_present,
            todo=plan.files_to_download,
            size=strings.format_size(plan.bytes_to_download),
        )
    )
    if plan.boundary_assets:
        print(strings.PLAN_BOUNDARY.format(count=plan.boundary_assets))
    if plan.compact_to_make:
        print(strings.PLAN_COMPACT.format(count=plan.compact_to_make, size=strings.format_size(plan.compact_bytes)))
    if plan.conflicts:
        print(strings.PLAN_CONFLICTS.format(count=len(plan.conflicts)))
        for path, reason in plan.conflicts[:20]:
            print(f"  {path}: {reason}")


def print_report(report: Report) -> None:
    print(
        strings.REPORT_SUMMARY.format(
            downloaded=report.downloaded,
            skipped=report.skipped,
            errors=len(report.errors),
            conflicts=len(report.conflicts),
        )
    )
    print(strings.REPORT_COMPACT.format(made=report.compact_made, errors=len(report.compact_errors)))
    for title, items in (("Ошибки", report.errors), ("Конфликты", report.conflicts), ("Ошибки JPG-копий", report.compact_errors)):
        if items:
            print(f"{title}:")
            for path, reason in items[:50]:
                print(f"  {path}: {reason}")
    if report.stopped_reason:
        print(strings.REPORT_STOPPED.format(reason=report.stopped_reason))


class ConsoleProgress:
    """Prints one status line every couple of seconds."""

    def __init__(self) -> None:
        self.total = 0
        self.done = 0
        self.bytes = 0
        self._last = 0.0
        self._lock = threading.Lock()

    def __call__(self, name: str, **data: Any) -> None:
        with self._lock:
            if name == "plan":
                self.total = data["plan"].files_to_download
                print_plan(data["plan"])
            elif name == "bytes":
                self.bytes += data["count"]
            elif name == "file" and data["result"] == "downloaded":
                self.done += 1
            elif name == "file" and data["result"] in ("error", "conflict"):
                print(f"  ! {data['path']}: {data.get('message', '')}")
            elif name == "status":
                label = {
                    "counting": strings.STATUS_COUNTING,
                    "downloading": strings.STATUS_DOWNLOADING,
                    "paused": strings.STATUS_PAUSED,
                }.get(data["state"])
                if label:
                    print(f"[{label}]")
            now = time.monotonic()
            if name in ("bytes", "file") and now - self._last > 2.0:
                self._last = now
                print(f"  {self.done} из {self.total} файлов, {strings.format_size(self.bytes)}")


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_accounts(_args: argparse.Namespace) -> int:
    cfg = config.load_config()
    if not cfg.accounts:
        print("Аккаунтов нет. Добавьте: python -m ipd_app login --account <Apple ID>")
    for key, account in cfg.accounts.items():
        mark = "*" if key == cfg.active_account else " "
        print(f"{mark} {account.apple_id}  папка: {account.root_dir or '(не выбрана)'}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    cfg = config.load_config()
    client = make_client(args.account)
    sign_in(client, args.account, PasswordStore())
    cfg.ensure_account(args.account)
    config.save_config(cfg)
    print("Вход выполнен, сессия сохранена.")
    return 0


def cmd_set_root(args: argparse.Namespace) -> int:
    cfg = config.load_config()
    account = cfg.ensure_account(args.account)
    account.root_dir = str(Path(args.path).resolve())
    config.save_config(cfg)
    print(f"Папка для {mask_apple_id(args.account)}: {account.root_dir}")
    for other in cfg.shared_roots(args.account):
        print(f"Внимание: ту же папку использует {mask_apple_id(other)}. Файлы обоих аккаунтов окажутся в одних папках месяцев.")
    return 0


def cmd_albums(args: argparse.Namespace) -> int:
    client = make_client(args.account)
    sign_in(client, args.account, PasswordStore())
    for album in client.list_albums():
        print(album.name)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    period = Period(parse_day(args.date_from), parse_day(args.date_to))
    if args.fake is not None:
        from .icloud_adapter.fake_client import demo_library

        if not args.root:
            print("Для --fake укажите --root.")
            return 2
        apple_id = FAKE_ACCOUNT
        client: ICloudClient = demo_library(args.fake)
        account = config.AccountConfig(apple_id=apple_id, root_dir=str(Path(args.root).resolve()))
        Path(account.root_dir).mkdir(parents=True, exist_ok=True)
        db_path = Path(account.root_dir).parent / (Path(account.root_dir).name + ".state.sqlite")
    else:
        if not args.account:
            print("Укажите --account или --fake.")
            return 2
        apple_id = args.account
        cfg = config.load_config()
        account = cfg.ensure_account(apple_id)
        if args.root:
            account.root_dir = str(Path(args.root).resolve())
        config.save_config(cfg)
        if not account.root_dir:
            print(strings.ERR_NO_ROOT)
            return 2
        client = make_client(apple_id)
        sign_in(client, apple_id, PasswordStore())
        db_path = config.state_db_path(apple_id)

    settings = account.to_settings()
    if args.concurrency:
        settings.concurrency = min(8, max(1, args.concurrency))
    if args.no_compact:
        settings.compact_enabled = False
    if args.edited:
        settings.edited = True

    db = StateDB(db_path)
    try:
        pending = db.unfinished_job()
        if pending and not args.dry_run:
            old = Period(parse_day(pending.date_from), parse_day(pending.date_to))
            print(strings.RESUME_PROMPT.format(period=old.label(), done=pending.done_files, total=pending.total_files))
            if args.resume:
                period = old
        engine = SyncEngine(client, db, settings, on_event=ConsoleProgress())
        print(f"Период: {period.label() if not period.unbounded else strings.PERIOD_ALL}. Папка: {settings.root}")
        if args.dry_run:
            print_plan(engine.preview(period))
            return 0
        try:
            report = engine.run(period)
        except KeyboardInterrupt:
            engine.stop()
            raise
        print_report(report)
        return 0 if report.finished and not report.errors else 1
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ipd_app", description="iCloud Photo Downloader (core CLI)")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--verbose", action="store_true", help="also print the log to the console")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("accounts", help="list saved accounts").set_defaults(func=cmd_accounts)

    login = sub.add_parser("login", help="sign in and save the session")
    login.add_argument("--account", required=True)
    login.set_defaults(func=cmd_login)

    root = sub.add_parser("set-root", help="choose the download folder of an account")
    root.add_argument("--account", required=True)
    root.add_argument("path")
    root.set_defaults(func=cmd_set_root)

    albums = sub.add_parser("albums", help="list albums of the personal library")
    albums.add_argument("--account", required=True)
    albums.set_defaults(func=cmd_albums)

    sync = sub.add_parser("sync", help="run a period job")
    sync.add_argument("--account")
    sync.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD")
    sync.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD")
    sync.add_argument("--root", help="download folder (saved for the account)")
    sync.add_argument("--dry-run", action="store_true", help="only show what would be downloaded")
    sync.add_argument("--resume", action="store_true", help="continue the unfinished job with its period")
    sync.add_argument("--concurrency", type=int)
    sync.add_argument("--no-compact", action="store_true")
    sync.add_argument("--edited", action="store_true", help="also fetch edited versions")
    sync.add_argument("--fake", type=int, metavar="N", help="use a generated library of N assets, no iCloud")
    sync.set_defaults(func=cmd_sync)

    gui = sub.add_parser("gui", help="open the application window (default when no command is given)")
    gui.add_argument("--fake", type=int, metavar="N", help="demo: generated library of N assets, password 'secret'")
    gui.add_argument("--hidden", action="store_true", help="start in the tray")
    gui.set_defaults(func=cmd_gui)

    check = sub.add_parser("selfcheck", help="offline check that every part of the installation works")
    check.add_argument("report", nargs="?", help="write the report to this file (the exe has no console)")
    check.set_defaults(func=cmd_selfcheck)

    forget = sub.add_parser("forget-credentials", help="remove saved passwords and sessions of all accounts")
    forget.set_defaults(func=cmd_forget_credentials)
    return parser


def cmd_selfcheck(args: argparse.Namespace) -> int:
    from .selfcheck import run_selfcheck

    return run_selfcheck(Path(args.report) if args.report else None)


def cmd_forget_credentials(_args: argparse.Namespace) -> int:
    """Used by the uninstaller when the user chooses to remove settings: passwords
    live in Windows Credential Manager, outside the folders the uninstaller removes."""
    from .accounts import forget_session

    store = PasswordStore()
    for account in config.load_config().accounts.values():
        store.forget(account.apple_id)
        forget_session(account.apple_id)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .ui.app import run_gui

    return run_gui(fake=args.fake, start_hidden=args.hidden)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if argv is None and len(sys.argv) == 1:
        argv = ["gui"]  # double-click on the exe: no arguments
    args = build_parser().parse_args(argv)
    if args.func is cmd_gui:
        return cmd_gui(args)  # the GUI sets up logging and its own error handler
    setup_logging(console=args.verbose)
    install_excepthook()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nПрервано.")
        return 130
    except PreflightError as error:
        print(f"ОШИБКА: {error.user_message}")
        return 2
    except ICloudError as error:
        log.error("iCloud error: %s", error)
        print(f"ОШИБКА: {error.user_message}")
        return 1
    except ValueError as error:
        print(f"ОШИБКА: {error}")
        return 2
