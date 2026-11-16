"""User-facing texts (Russian). Kept in one place for future localisation.

Code, comments and log messages stay in English; only what the user reads lives here.
"""

from __future__ import annotations

ERR_BAD_CREDENTIALS = "Неверный Apple ID или пароль."
ERR_BAD_2FA_CODE = "Код подтверждения не принят."
ERR_PASSWORD_STORAGE = "Не удалось сохранить пароль в системном хранилище. Проверьте доступ к нему."
ERR_SESSION_EXPIRED = "Сессия истекла, войдите заново."
ERR_ADP = (
    "Включена Advanced Data Protection. С ней веб-доступ к фото закрыт. "
    "Выключите её в настройках iCloud на iPhone."
)
ERR_WEB_ACCESS = (
    "Веб-доступ к iCloud выключен. Включите «Доступ к данным iCloud через веб» "
    "в настройках iCloud на iPhone."
)
ERR_SECURITY_KEY = "Вход через аппаратные ключи безопасности не поддерживается."
ERR_NETWORK = "Нет связи с серверами iCloud. Проверьте интернет."
ERR_UNAVAILABLE = "iCloud временно недоступен или ограничил запросы. Повторите позже."
ERR_LIBRARY_NOT_READY = "Медиатека iCloud ещё не готова (идёт индексация). Повторите позже."
ERR_ICLOUD_GENERIC = "Ошибка iCloud: {detail}"

ERR_NO_ROOT = "Не выбрана папка для загрузки. Выберите её в настройках аккаунта."
ERR_ROOT_UNAVAILABLE = "Папка {path} недоступна. Проверьте диск или сетевое подключение."
ERR_ROOT_NOT_WRITABLE = "В папку {path} нельзя записывать. Проверьте права доступа."
ERR_LOW_SPACE = "Мало места на диске: свободно {free}, нужно не меньше {need}."
ERR_PATH_TOO_LONG = "Слишком длинный путь: {path}"
ERR_BAD_PERIOD = "Начало периода позже конца."
ERR_JOB_RUNNING = "Задание уже выполняется."

STATUS_IDLE = "Ожидание"
STATUS_COUNTING = "Подсчёт новых файлов"
STATUS_DOWNLOADING = "Загрузка"
STATUS_PAUSED = "Пауза"
STATUS_ERROR = "Ошибка"

REASON_SAME_SIZE_CONFLICT = "по этому пути лежит файл другого размера"
REASON_SIZE_MISMATCH = "размер скачанного файла не совпал: {got} из {expected} байт"
REASON_NO_VERSION = "в iCloud нет этой версии файла"

PLAN_SUMMARY = (
    "В периоде: {total} файлов. Уже есть в папке: {present}. "
    "К загрузке: {todo} файлов, {size}."
)
PLAN_BOUNDARY = "На границе периода: {count} (решение по времени съёмки из файла)."
PLAN_COMPACT = "JPG-копий создать: {count}, примерно {size}."
PLAN_CONFLICTS = "Конфликтов: {count}."
REPORT_SUMMARY = "Скачано: {downloaded}. Пропущено: {skipped}. Ошибок: {errors}. Конфликтов: {conflicts}."
REPORT_COMPACT = "JPG-копий создано: {made}, ошибок: {errors}."
REPORT_STOPPED = "Задание остановлено: {reason}"
RESUME_PROMPT = "Продолжить задание {period}? Скачано {done} из {total}."

STOP_USER = "остановлено пользователем"
STOP_SESSION = ERR_SESSION_EXPIRED
PERIOD_ALL = "весь период"


class UI:
    """Texts of the windows, tray and notifications."""

    APP_TITLE = "iCloud Photo Downloader"

    # main window
    ACCOUNT = "Аккаунт:"
    NO_ACCOUNTS = "Нет аккаунтов"
    BTN_ACCOUNTS = "Аккаунты…"
    BTN_SETTINGS = "Настройки…"
    BTN_LOG = "Журнал…"
    BTN_SIGN_IN = "Войти"
    SESSION_UNKNOWN = "Сессия: не проверена"
    SESSION_CHECKING = "Сессия: проверка…"
    SESSION_OK = "Сессия: активна"
    SESSION_EXPIRED = "Сессия: нужен вход"
    SESSION_ERROR = "Сессия: {message}"
    GROUP_JOB = "Задание на период"
    DATE_FROM = "С"
    DATE_TO = "по"
    ALL_TIME = "Весь период"
    PRESET_THIS_YEAR = "Этот год"
    PRESET_LAST_YEAR = "Прошлый год"
    PRESET_30_DAYS = "Последние 30 дней"
    BTN_START = "Запустить задание"
    BTN_PAUSE = "Пауза"
    BTN_RESUME = "Продолжить"
    BTN_STOP = "Остановить"
    HINT_BAD_PERIOD = "Начало периода позже конца."
    HINT_NO_ACCOUNT = "Добавьте аккаунт, чтобы запустить задание."
    HINT_NO_ROOT = "Выберите папку для загрузки в настройках."
    HINT_NO_SESSION = "Войдите в аккаунт, чтобы запустить задание."
    GROUP_PROGRESS = "Ход работы"
    STATUS = "Состояние: {state}"
    PROGRESS_FILES = "Файлов: {done} из {total}"
    PROGRESS_BYTES = "Объём: {done} из {total}"
    PROGRESS_SPEED = "Скорость: {speed}/с"
    PROGRESS_ETA = "Осталось: {eta}"
    PROGRESS_CURRENT = "Сейчас: {name}"
    DASH = "—"
    GROUP_LAST = "Последний запуск"
    LAST_NONE = "Заданий ещё не было."
    LAST_SUMMARY = "Скачано: {downloaded} · Пропущено: {skipped} · Ошибок: {errors} · Конфликтов: {conflicts}"
    LAST_COMPACT = "JPG-копий создано: {made}, ошибок: {errors}"
    LAST_STOPPED = "Остановлено: {reason}"
    BTN_SHOW_ERRORS = "Показать ошибки"
    BTN_OPEN_FOLDER = "Открыть папку"
    ERRORS_TITLE = "Ошибки и конфликты"
    ERRORS_COLUMNS = ("Файл", "Вид", "Причина")
    KIND_ERROR = "ошибка"
    KIND_CONFLICT = "конфликт"
    KIND_COMPACT = "JPG-копия"
    ETA_SECONDS = "{s} с"
    ETA_MINUTES = "{m} мин {s} с"
    ETA_HOURS = "{h} ч {m} мин"

    # login
    LOGIN_TITLE = "Вход в iCloud"
    APPLE_ID = "Apple ID:"
    PASSWORD = "Пароль:"
    BTN_LOGIN = "Войти"
    BTN_CANCEL = "Отмена"
    LOGIN_WAIT = "Подключение к iCloud…"
    LOGIN_NEED_FIELDS = "Введите Apple ID и пароль."
    CODE_PROMPT = "Введите 6-значный код, который пришёл на ваше устройство Apple."
    CODE_FIELD = "Код:"
    BTN_CONFIRM = "Подтвердить"
    BTN_SEND_SMS = "Прислать SMS на {number}"
    SMS_SENT = "SMS отправлено на {number}. Введите код из сообщения."
    CODE_WAIT = "Проверка кода…"
    CODE_NEED_6 = "Нужно 6 цифр."
    REQUIREMENTS_NOTE = (
        "На iPhone должен быть включён «Доступ к данным iCloud через веб», "
        "а Advanced Data Protection выключена."
    )

    # accounts
    ACCOUNTS_TITLE = "Аккаунты"
    ACTIVE_MARK = " (активный)"
    BTN_ADD = "Добавить…"
    BTN_SWITCH = "Сделать активным"
    BTN_LOGOUT = "Выйти"
    BTN_REMOVE = "Удалить"
    BTN_CLOSE = "Закрыть"
    CONFIRM_LOGOUT = "Выйти из аккаунта {account}? Сохранённый пароль и сессия будут удалены."
    CONFIRM_REMOVE = (
        "Удалить аккаунт {account} из программы?\n\n"
        "Будут удалены сохранённый пароль, сессия и настройки аккаунта. "
        "Скачанные фото и видео останутся на месте."
    )
    SWITCH_WHILE_RUNNING = "Сначала остановите задание."
    CHOOSE_ROOT_FIRST = "Выберите папку, в которую будут загружаться фото этого аккаунта."

    # settings
    SETTINGS_TITLE = "Настройки: {account}"
    TAB_FOLDER = "Папка"
    TAB_COMPACT = "Compact"
    TAB_FILTERS = "Что скачивать"
    TAB_DOWNLOAD = "Загрузка"
    ROOT_LABEL = "Корневая папка аккаунта:"
    ROOT_EMPTY = "(не выбрана)"
    BTN_CHOOSE = "Выбрать…"
    ROOT_DIALOG = "Папка для фото"
    ROOT_NOTE = "Внутри неё программа создаёт папки вида 2023\\03 March\\Full size и Compact."
    SHARED_ROOT_WARNING = (
        "Эту же папку использует {others}. Файлы обоих аккаунтов окажутся в одних и тех же папках месяцев."
    )
    COMPACT_ENABLED = "Создавать JPG-копии фото в папке Compact"
    COMPACT_SIZE = "Размер по длинной стороне:"
    COMPACT_SIZE_ORIGINAL = "Без уменьшения"
    COMPACT_SIZE_PX = "{px} px"
    COMPACT_QUALITY = "Качество JPG:"
    COMPACT_NOTE = "Если выключить, новые копии не создаются, а уже созданные остаются."
    MEDIA_PHOTOS = "Фото"
    MEDIA_VIDEOS = "Видео"
    LIVE_VIDEO = "Скачивать видеочасть Live Photos"
    EDITED = "Также скачивать отредактированную версию (с суффиксом _edited)"
    SOURCE_ALL = "Вся личная медиатека"
    SOURCE_ALBUMS = "Только выбранные альбомы:"
    BTN_LOAD_ALBUMS = "Загрузить список альбомов"
    ALBUMS_LOADING = "Загрузка списка альбомов…"
    ALBUMS_FAILED = "Не удалось получить альбомы: {message}"
    ALWAYS_EXCLUDED = "«Скрытые», «Недавно удалённые» и общие альбомы не скачиваются никогда."
    CONCURRENCY = "Одновременных загрузок:"
    MIN_FREE = "Останавливаться, если свободно меньше:"
    GB = " ГБ"
    RESTORE_DELETED = "Скачивать заново файлы, удалённые из папки вручную"
    BTN_SAVE = "Сохранить"
    SETTINGS_LOCKED = "Идёт задание: настройки можно менять после его остановки."

    # log
    LOG_TITLE = "Журнал"
    LOG_LEVEL = "Уровень:"
    LOG_LEVELS = ("Все", "INFO и выше", "WARNING и выше", "Только ошибки")
    BTN_REFRESH = "Обновить"
    BTN_OPEN_LOGS = "Открыть папку с логами"

    # tray and notifications
    TRAY_OPEN = "Открыть"
    TRAY_EXIT = "Выход"
    TRAY_TIP_IDLE = "iCloud Photo Downloader: ожидание"
    TRAY_TIP_ACTIVE = "iCloud Photo Downloader: загрузка, {done} из {total}"
    TRAY_TIP_ERROR = "iCloud Photo Downloader: ошибка"
    NOTE_DONE_TITLE = "Задание завершено"
    NOTE_STOPPED_TITLE = "Задание остановлено"
    NOTE_ERROR_TITLE = "Ошибка"
    NOTE_RELOGIN_TITLE = "Нужен повторный вход"
    NOTE_RELOGIN_TEXT = "Сессия iCloud истекла. Нажмите, чтобы войти заново."
    NOTE_TO_TRAY = "Программа продолжает работать в трее."
    CONFIRM_EXIT_RUNNING = "Идёт задание. Остановить его и выйти?"
    RESUME_TITLE = "Незавершённое задание"
    UNHANDLED_TITLE = "Непредвиденная ошибка"
    UNHANDLED_TEXT = "Произошла ошибка, подробности записаны в журнал.\n\n{detail}"
    ALREADY_RUNNING = "Программа уже запущена."


def format_size(num_bytes: float) -> str:
    """1 536 000 -> '1,5 МБ'."""
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    value = float(num_bytes)
    for unit in units:
        if abs(value) < 1024 or unit == units[-1]:
            if unit == "Б":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{value:.1f} ТБ"
