"""Turkish."""

from __future__ import annotations

LOCALE = "tr_TR"
DATE_FORMAT = "%d.%m.%Y"
SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")
DECIMAL_SEPARATOR = ","

ERR_BAD_CREDENTIALS = "Apple Hesabı e-posta adresi veya parola hatalı."
ERR_BAD_2FA_CODE = "Doğrulama kodu kabul edilmedi."
ERR_SESSION_EXPIRED = "Oturumun süresi doldu, lütfen yeniden oturum açın."
ERR_ADP = (
    "İleri Düzey Veri Koruması açık. Bu özellik fotoğraflara web erişimini engeller. "
    "iPhone'unuzdaki iCloud ayarlarından kapatın."
)
ERR_WEB_ACCESS = (
    "iCloud'a web erişimi kapalı. iPhone'unuzdaki iCloud ayarlarından "
    "“Web'de iCloud Verilerine Eriş” seçeneğini açın."
)
ERR_SECURITY_KEY = "Donanım güvenlik anahtarlarıyla oturum açma desteklenmiyor."
ERR_NETWORK = "iCloud sunucularına ulaşılamıyor. İnternet bağlantınızı denetleyin."
ERR_UNAVAILABLE = "iCloud geçici olarak kullanılamıyor veya istekleri sınırlıyor. Daha sonra yeniden deneyin."
ERR_LIBRARY_NOT_READY = (
    "iCloud arşivi henüz hazır değil (dizinleme sürüyor). Daha sonra yeniden deneyin."
)
ERR_LINK_EXPIRED = "Dosyanın sırası gelmeden indirme bağlantısının süresi doldu. Görevi yeniden başlatın."
ERR_ICLOUD_GENERIC = "iCloud hatası: {detail}"

ERR_NO_ROOT = "İndirme klasörü seçilmedi. Hesap ayarlarından bir klasör seçin."
ERR_ROOT_UNAVAILABLE = (
    "Klasör kullanılamıyor: {path}. Diski veya ağ bağlantısını denetleyin."
)
ERR_ROOT_NOT_WRITABLE = "Klasöre yazılamıyor: {path}. Erişim izinlerini denetleyin."
ERR_LOW_SPACE = "Disk alanı yetersiz: boş alan {free}, en az {need} gerekli."
ERR_PATH_TOO_LONG = "Yol çok uzun: {path}"
ERR_BAD_PERIOD = "Başlangıç tarihi bitiş tarihinden sonra olamaz."
ERR_JOB_RUNNING = "Zaten çalışan bir görev var."

STATUS_IDLE = "Boşta"
STATUS_COUNTING = "Yeni dosyalar sayılıyor"
STATUS_DOWNLOADING = "İndiriliyor"
STATUS_SEARCHING = "Eksik dosyalar aranıyor"
STATUS_PAUSED = "Duraklatıldı"
STATUS_ERROR = "Hata"

REASON_SAME_SIZE_CONFLICT = "bu yolda farklı boyutta bir dosya zaten var"
REASON_SIZE_MISMATCH = "indirilen dosyanın boyutu hatalı: {got} / {expected} bayt"
REASON_NO_VERSION = "iCloud'da dosyanın bu sürümü yok"

PLAN_SUMMARY = (
    "Dönemdeki dosyalar: {total}. Klasörde zaten var: {present}. "
    "İndirilecek: {todo} ({size})."
)
PLAN_BOUNDARY = "Dönem sınırındaki dosyalar: {count} (dosyada kayıtlı çekim tarihine göre değerlendirilecek)."
PLAN_COMPACT = "Oluşturulacak JPG kopyaları: {count}, yaklaşık {size}."
PLAN_CONFLICTS = "Çakışmalar: {count}."
REPORT_SUMMARY = "İndirilen: {downloaded}. Atlanan: {skipped}. Hatalar: {errors}. Çakışmalar: {conflicts}."
REPORT_COMPACT = "Oluşturulan JPG kopyaları: {made}, hatalar: {errors}."
REPORT_STOPPED = "Görev durduruldu: {reason}"
RESUME_PROMPT = "Göreve devam edilsin mi? Dönem: {period}. İndirilen: {done} / {total}."

STOP_USER = "kullanıcı isteğiyle"
PERIOD_ALL = "tüm zamanlar"


class UI:
    APP_TITLE = "iCloud Photo Downloader"
    DATE_DISPLAY = "dd.MM.yyyy"

    # language
    LANGUAGE = "Dil:"
    LANGUAGE_AUTO = "Windows ile aynı"
    LANGUAGE_RESTART = "Dil, program yeniden başlatıldıktan sonra değişecek."

    # main window
    ACCOUNT = "Hesap:"
    NO_ACCOUNTS = "Hesap yok"
    BTN_ACCOUNTS = "Hesaplar…"
    BTN_SETTINGS = "Ayarlar…"
    BTN_LOG = "Günlük…"
    BTN_SIGN_IN = "Oturum aç"
    SESSION_UNKNOWN = "Oturum: denetlenmedi"
    SESSION_CHECKING = "Oturum: denetleniyor…"
    SESSION_OK = "Oturum: etkin"
    SESSION_EXPIRED = "Oturum: giriş gerekiyor"
    SESSION_ERROR = "Oturum: {message}"
    GROUP_JOB = "İndirme dönemi"
    DATE_FROM = "Başlangıç"
    DATE_TO = "Bitiş"
    ALL_TIME = "Tüm zamanlar"
    PRESET_LAST_YEAR = "Geçen yıl"
    PRESET_30_DAYS = "Son 30 gün"
    BTN_START = "Görevi başlat"
    BTN_PAUSE = "Duraklat"
    BTN_RESUME = "Devam et"
    BTN_STOP = "Durdur"
    HINT_BAD_PERIOD = "Başlangıç tarihi bitiş tarihinden sonra olamaz."
    HINT_NO_ACCOUNT = "Görev başlatmak için bir hesap ekleyin."
    HINT_NO_ROOT = "Ayarlardan bir indirme klasörü seçin."
    HINT_NO_SESSION = "Görev başlatmak için hesapta oturum açın."
    GROUP_PROGRESS = "İlerleme"
    STATUS = "Durum: {state}"
    PROGRESS_FILES = "Dosyalar: {done} / {total}"
    PROGRESS_BYTES = "Boyut: {done} / {total}"
    PROGRESS_SPEED = "Hız: {speed}/sn"
    PROGRESS_ETA = "Kalan süre: {eta}"
    PROGRESS_CURRENT = "Şu anda: {name}"
    PROGRESS_CHECKED = "Denetlenen: {count}"
    DASH = "—"
    GROUP_LAST = "Son çalıştırma"
    LAST_NONE = "Henüz hiç görev çalıştırılmadı."
    LAST_SUMMARY = "İndirilen: {downloaded} · Atlanan: {skipped} · Hatalar: {errors} · Çakışmalar: {conflicts}"
    LAST_COMPACT = "Oluşturulan JPG kopyaları: {made}, hatalar: {errors}"
    LAST_STOPPED = "Durduruldu: {reason}"
    BTN_SHOW_ERRORS = "Hataları göster"
    BTN_OPEN_FOLDER = "Klasörü aç"
    ERRORS_TITLE = "Hatalar ve çakışmalar"
    ERRORS_COLUMNS = ("Dosya", "Tür", "Neden")
    KIND_ERROR = "hata"
    KIND_CONFLICT = "çakışma"
    KIND_COMPACT = "JPG kopyası"
    ETA_SECONDS = "{s} sn"
    ETA_MINUTES = "{m} dk {s} sn"
    ETA_HOURS = "{h} sa {m} dk"

    # login
    LOGIN_TITLE = "iCloud'da oturum aç"
    APPLE_ID = "Apple Hesabı:"
    PASSWORD = "Parola:"
    BTN_LOGIN = "Oturum aç"
    BTN_CANCEL = "İptal"
    LOGIN_WAIT = "iCloud'a bağlanılıyor…"
    LOGIN_NEED_FIELDS = "Apple Hesabı e-posta adresinizi ve parolanızı girin."
    CODE_PROMPT = "Apple aygıtınıza gönderilen 6 haneli kodu girin."
    CODE_FIELD = "Kod:"
    BTN_CONFIRM = "Onayla"
    BTN_SEND_SMS = "SMS gönder: {number}"
    SMS_SENT = "SMS gönderildi: {number}. Mesajdaki kodu girin."
    CODE_WAIT = "Kod denetleniyor…"
    CODE_NEED_6 = "Kod 6 haneli olmalıdır."
    REQUIREMENTS_NOTE = (
        "iPhone'unuzda “Web'de iCloud Verilerine Eriş” açık, "
        "İleri Düzey Veri Koruması ise kapalı olmalıdır."
    )

    # accounts
    ACCOUNTS_TITLE = "Hesaplar"
    ACTIVE_MARK = " (etkin)"
    BTN_ADD = "Ekle…"
    BTN_SWITCH = "Bu hesaba geç"
    BTN_LOGOUT = "Oturumu kapat"
    BTN_REMOVE = "Kaldır"
    BTN_CLOSE = "Kapat"
    CONFIRM_LOGOUT = "{account} hesabında oturum kapatılsın mı? Kayıtlı parola ve oturum bilgileri silinecek."
    CONFIRM_REMOVE = (
        "{account} hesabı programdan kaldırılsın mı?\n\n"
        "Kayıtlı parola, oturum ve hesap ayarları silinecek. "
        "İndirilen fotoğraflar ve videolar yerinde kalacak."
    )
    SWITCH_WHILE_RUNNING = "Önce görevi durdurun."
    CHOOSE_ROOT_FIRST = "Bu hesabın fotoğraflarının indirileceği klasörü seçin."

    # settings
    SETTINGS_TITLE = "Ayarlar: {account}"
    TAB_FOLDER = "Klasör"
    TAB_COMPACT = "JPG kopyaları"
    TAB_FILTERS = "İçerik"
    TAB_DOWNLOAD = "İndirme"
    ROOT_LABEL = "İndirme klasörü:"
    ROOT_EMPTY = "(seçilmedi)"
    BTN_CHOOSE = "Seç…"
    ROOT_DIALOG = "İndirme klasörünü seçin"
    ROOT_NOTE = "Program bu klasörün içinde 2023\\03 March\\Full size ve Compact gibi klasörler oluşturur."
    SHARED_ROOT_WARNING = "Bu klasör başka hesaplarca da kullanılıyor: {others}. Bu hesapların dosyaları aynı ay klasörlerine kaydedilecek."
    COMPACT_ENABLED = "Fotoğrafların JPG kopyalarını Compact klasöründe oluştur"
    COMPACT_SIZE = "Uzun kenar boyutu:"
    COMPACT_SIZE_ORIGINAL = "Özgün boyut"
    COMPACT_SIZE_PX = "{px} px"
    COMPACT_QUALITY = "JPG kalitesi:"
    COMPACT_NOTE = "Kapatılırsa yeni kopya oluşturulmaz; mevcut kopyalar korunur."
    MEDIA_PHOTOS = "Fotoğraflar"
    MEDIA_VIDEOS = "Videolar"
    LIVE_VIDEO = "Live Photo'ların video bölümünü de indir"
    EDITED = "Düzenlenmiş sürümü de indir (_edited son ekiyle)"
    SOURCE_ALL = "Kişisel arşivin tamamı"
    SOURCE_ALBUMS = "Yalnızca seçili albümler:"
    BTN_LOAD_ALBUMS = "Albüm listesini yükle"
    ALBUMS_LOADING = "Albüm listesi yükleniyor…"
    ALBUMS_FAILED = "Albümler alınamadı: {message}"
    ALWAYS_EXCLUDED = (
        "“Gizli”, “Son Silinenler” ve paylaşılan albümler hiçbir zaman indirilmez."
    )
    CONCURRENCY = "Eşzamanlı indirme sayısı:"
    MIN_FREE = "Boş alan şu değerin altına düşünce durdur:"
    GB = " GB"
    RESTORE_DELETED = "Klasörden elle silinen dosyaları yeniden indir"
    BTN_SAVE = "Kaydet"
    SETTINGS_LOCKED = (
        "Bir görev çalışıyor: ayarlar görev durduktan sonra değiştirilebilir."
    )

    # log
    LOG_TITLE = "Günlük"
    LOG_LEVEL = "Düzey:"
    LOG_LEVELS = ("Tümü", "INFO ve üzeri", "WARNING ve üzeri", "Yalnızca hatalar")
    BTN_REFRESH = "Yenile"
    BTN_OPEN_LOGS = "Günlük klasörünü aç"

    # tray and notifications
    TRAY_OPEN = "Aç"
    TRAY_EXIT = "Çıkış"
    TRAY_TIP_IDLE = "iCloud Photo Downloader: boşta"
    TRAY_TIP_ACTIVE = "iCloud Photo Downloader: indiriliyor, {done} / {total}"
    TRAY_TIP_ERROR = "iCloud Photo Downloader: hata"
    NOTE_DONE_TITLE = "Görev tamamlandı"
    NOTE_STOPPED_TITLE = "Görev durduruldu"
    NOTE_ERROR_TITLE = "Hata"
    NOTE_RELOGIN_TITLE = "Oturum açılması gerekiyor"
    NOTE_RELOGIN_TEXT = (
        "iCloud oturumunun süresi doldu. Yeniden oturum açmak için tıklayın."
    )
    NOTE_TO_TRAY = "Program sistem tepsisinde çalışmaya devam ediyor."
    CONFIRM_EXIT_RUNNING = "Bir görev çalışıyor. Durdurulup çıkılsın mı?"
    RESUME_TITLE = "Tamamlanmamış görev"
    UNHANDLED_TITLE = "Beklenmeyen hata"
    UNHANDLED_TEXT = "Bir hata oluştu; ayrıntılar günlüğe yazıldı.\n\n{detail}"
    ALREADY_RUNNING = "Program zaten çalışıyor."
