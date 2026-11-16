"""Translations: nothing missing, same placeholders, and switching really switches."""

from __future__ import annotations

import re
import string

import pytest

from ipd_app import config, strings
from ipd_app.icloud_adapter.errors import BadCredentialsError, ICloudError
from ipd_app.locales import en, es, pt_br, zh_cn
from datetime import date

from ipd_app.sync_engine import Period

TRANSLATIONS = {"en": en, "es": es, "pt_BR": pt_br, "zh_CN": zh_cn}
# Identical in every language on purpose: names, units, technical words.
SAME_AS_RUSSIAN_OK = {
    "APP_TITLE", "APPLE_ID", "TAB_COMPACT", "DASH", "COMPACT_SIZE_PX", "ETA_SECONDS", "DATE_FORMAT",
    "DATE_DISPLAY", "DECIMAL_SEPARATOR", "STATUS_ERROR", "NOTE_ERROR_TITLE", "KIND_ERROR",
}  # fmt: skip
CYRILLIC = re.compile("[А-Яа-яЁё]")


def placeholders(text: str) -> list[str]:
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def pairs(module):
    """(name, russian, translated) for module-level texts and for the UI class."""
    for name, russian in strings._RUSSIAN.items():
        yield name, russian, getattr(module, name, None)
    for name, russian in strings._RUSSIAN_UI.items():
        yield f"UI.{name}", russian, getattr(module.UI, name, None)


def test_every_listed_language_has_a_translation() -> None:
    assert set(strings.LANGUAGES) == {strings.DEFAULT_LANGUAGE, *TRANSLATIONS}


@pytest.mark.parametrize("code", TRANSLATIONS)
def test_translation_is_complete_and_keeps_placeholders(code) -> None:
    for name, russian, translated in pairs(TRANSLATIONS[code]):
        assert translated is not None, f"{code}: {name} is not translated"
        assert type(translated) is type(russian), f"{code}: {name} has another type"
        if isinstance(russian, tuple):
            assert len(translated) == len(russian), f"{code}: {name} has another length"
            assert all(isinstance(item, str) and item for item in translated)
            continue
        assert translated.strip(), f"{code}: {name} is empty"
        assert placeholders(translated) == placeholders(russian), f"{code}: {name} has other placeholders"
        assert translated.count("\n") == russian.count("\n"), f"{code}: {name} has other line breaks"
        assert not CYRILLIC.search(translated), f"{code}: {name} still has Russian letters"
        if name.split(".")[-1] not in SAME_AS_RUSSIAN_OK:
            assert translated != russian, f"{code}: {name} is the same as the Russian text"


@pytest.mark.parametrize("code", TRANSLATIONS)
def test_translation_has_no_extra_names(code) -> None:
    module = TRANSLATIONS[code]
    own = {name for name in vars(module) if name.isupper() and name != "UI"}
    own_ui = {name for name in vars(module.UI) if name.isupper()}
    assert own <= set(strings._RUSSIAN) and own_ui <= set(strings._RUSSIAN_UI)


def test_switching_changes_texts_everywhere_and_back() -> None:
    russian_title, russian_error = strings.UI.BTN_START, strings.ERR_NETWORK
    assert strings.set_language("en") == "en"
    assert strings.current_language == "en"
    assert strings.UI.BTN_START == en.UI.BTN_START != russian_title
    assert strings.ERR_NETWORK == en.ERR_NETWORK != russian_error
    assert strings.STOP_SESSION == strings.ERR_SESSION_EXPIRED == en.ERR_SESSION_EXPIRED
    assert strings.format_size(1536 * 1024) == "1.5 MB"
    assert Period(date(2024, 1, 5), date(2024, 2, 6)).label() == "2024-01-05–2024-02-06"
    # errors take their text when raised, not when the module was imported
    assert BadCredentialsError().user_message == en.ERR_BAD_CREDENTIALS
    assert ICloudError("boom").user_message == "iCloud error: boom"

    assert strings.set_language("ru") == "ru"
    assert strings.UI.BTN_START == russian_title and strings.ERR_NETWORK == russian_error
    assert strings.format_size(1536 * 1024) == "1,5 МБ"
    assert BadCredentialsError().user_message == strings.ERR_BAD_CREDENTIALS


def test_unknown_language_means_the_default() -> None:
    strings.set_language("zh_CN")
    assert strings.set_language("klingon") == strings.DEFAULT_LANGUAGE
    assert strings.UI.BTN_STOP == strings._RUSSIAN_UI["BTN_STOP"]


@pytest.mark.parametrize(
    ("choice", "system", "expected"),
    [
        ("auto", "ru_RU", "ru"),
        ("auto", "en_GB", "en"),
        ("auto", "es_MX", "es"),
        ("auto", "pt_BR", "pt_BR"),
        ("auto", "pt_PT", "pt_BR"),
        ("auto", "zh_TW", "zh_CN"),
        ("auto", "zh-CN", "zh_CN"),
        ("auto", "de_DE", "en"),
        ("auto", "", "en"),
        (None, "fr_FR", "en"),
        ("es", "ru_RU", "es"),
        ("nonsense", "ru_RU", "ru"),
    ],
)
def test_language_choice(choice, system, expected) -> None:
    assert strings.resolve_language(choice, system) == expected


def test_system_language_never_raises() -> None:
    assert isinstance(strings.system_language(), str)


def test_language_is_saved_in_the_config(tmp_path) -> None:
    path = tmp_path / "config.json"
    assert config.load_config(path).language == "auto"
    cfg = config.AppConfig(language="pt_BR")
    config.save_config(cfg, path)
    assert config.load_config(path).language == "pt_BR"
