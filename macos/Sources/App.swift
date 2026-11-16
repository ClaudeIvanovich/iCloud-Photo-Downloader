import SwiftUI
import AppKit
@preconcurrency import UserNotifications

typealias LegacyState<Value> = SwiftUI.State<Value>

struct LocalMessage: Codable {
    var ru: String = ""
    var en: String = ""
    func text(_ language: String) -> String { language == "en" ? en : ru }
}
struct Account: Codable, Identifiable, Equatable {
    var id: String { appleId }
    var appleId: String
    var rootDir: String = ""
    var photos: Bool = true
    var videos: Bool = true
    var albums: [String]? = nil
    var liveVideo: Bool = true
    var edited: Bool = false
    var compactEnabled: Bool = true
    var compactLongSide: Int? = 2048
    var compactQuality: Int = 85
    var concurrency: Int = 3
    var minFreeGb: Double = 5
    var restoreDeleted: Bool = true
}
struct Album: Codable, Identifiable { var id: String; var name: String }
struct Phone: Codable, Identifiable { var id: Int; var maskedNumber: String }

let translations: [String: String] = [
    "Accounts": "Аккаунты", "Add account": "Добавить аккаунт", "Sign in": "Войти", "Sign out": "Выйти", "Remove account": "Удалить аккаунт", "Apple ID": "Apple ID", "Password": "Пароль", "Cancel": "Отмена", "Close": "Закрыть", "Save": "Сохранить", "Language": "Язык", "Settings": "Настройки", "Folder": "Папка", "Download folder": "Папка для загрузки", "Choose folder": "Выбрать папку", "iCloud photo download folder": "Папка для фотографий iCloud", "Choose where to save photos and videos downloaded from iCloud.": "Выберите папку, куда приложение будет сохранять фотографии и видео из iCloud.", "The app creates folders by year and month, with originals in Full size and JPEG copies in Compact.": "Внутри приложение создаст папки по годам и месяцам: оригиналы сохранятся в Full size, а JPG-копии — в Compact.", "Choose": "Выбрать", "Open folder": "Открыть папку", "No folder selected": "Папка не выбрана", "Media": "Медиа", "Photos": "Фото", "Videos": "Видео", "Include Live Photo video": "Скачивать видео Live Photo", "Include edited versions": "Скачивать отредактированные версии", "Album selection": "Выбор альбомов", "All photos": "Вся медиатека", "Selected albums": "Выбранные альбомы", "Load albums": "Загрузить альбомы", "Hidden, recently deleted and shared albums are excluded.": "Скрытые и недавно удалённые файлы и общие альбомы не скачиваются.", "Compact JPEG copies": "JPG-копии Compact", "Create JPEG copies": "Создавать JPG-копии", "Long edge": "Длинная сторона", "Original size": "Без уменьшения", "JPEG quality": "Качество JPG", "Downloads": "Загрузка", "Parallel downloads": "Одновременных загрузок", "Minimum free space (GB)": "Минимум свободного места (ГБ)", "Restore manually deleted files": "Восстанавливать файлы, удалённые вручную", "Period": "Период", "All time": "Весь период", "From": "С", "To": "По", "Start": "Начать", "Pause": "Пауза", "Resume": "Продолжить", "Stop": "Остановить", "Progress": "Ход работы", "Waiting": "Ожидание", "Counting": "Подсчёт", "Items checked": "Проверено объектов", "Checking a large library can take time. The counter updates as items are checked.": "Проверка большой медиатеки может занять время. Счётчик обновляется по мере обработки.", "Downloading": "Загрузка", "Paused": "Пауза", "Error": "Ошибка", "Session unchecked": "Сессия не проверена", "Checking session": "Проверка сессии", "Session active": "Сессия активна", "Sign-in required": "Требуется вход", "Files": "Файлов", "Size": "Объём", "Current file": "Текущий файл", "Download plan": "План загрузки", "In period": "В периоде", "Already present": "Уже есть", "To download": "К загрузке", "Compact copies": "Копий Compact", "Last run": "Последний запуск", "Downloaded": "Скачано", "Skipped": "Пропущено", "Errors": "Ошибки", "Conflicts": "Конфликты", "Show details": "Показать подробности", "No jobs yet": "Заданий ещё не было", "Verification code": "Код подтверждения", "Enter the six-digit code from your Apple device.": "Введите шестизначный код с устройства Apple.", "Confirm": "Подтвердить", "Send SMS": "Отправить SMS", "SMS code": "Код из SMS", "Open": "Открыть", "Quit": "Выход", "View logs": "Открыть журнал", "Application log": "Журнал приложения", "Refresh": "Обновить", "Open log folder": "Открыть папку журналов", "Shared folder warning": "Эту папку использует другой аккаунт", "Remove this account? Downloaded files will remain.": "Удалить аккаунт? Скачанные файлы останутся на месте.", "Sign out of this account?": "Выйти из аккаунта?", "Remove": "Удалить", "Show settings": "Открыть настройки", "The job is running. Stop it before changing accounts or settings.": "Идёт загрузка. Остановите задание перед сменой аккаунта или настроек.", "iCloud web access must be enabled. Advanced Data Protection and security keys are not supported.": "Доступ к данным iCloud через веб должен быть включён. Advanced Data Protection и аппаратные ключи не поддерживаются.", "Job complete": "Задание завершено", "Job stopped": "Задание остановлено", "The background service stopped.": "Фоновый процесс остановился.", "Could not start the background service.": "Не удалось запустить фоновый процесс.", "Details": "Подробности", "Done": "Готово", "Send code": "Отправить код", "Both dates are inclusive.": "Обе границы периода включены.", "A job is running. Stop it and quit?": "Идёт загрузка. Остановить её и выйти?", "Stop and quit": "Остановить и выйти", "No account selected": "Аккаунт не выбран", "Select at least one album.": "Выберите хотя бы один альбом.", "Connection error": "Ошибка соединения", "Preparing": "Подготовка", "Preview": "Предварительный подсчёт", "Resume unfinished job?": "Продолжить незавершённое задание?", "This year": "Этот год", "Last year": "Прошлый год", "Last 30 days": "Последние 30 дней", "Speed": "Скорость", "Remaining": "Осталось"
]
func tr(_ key: String, _ language: String) -> String { language == "ru" ? (translations[key] ?? key) : key }

func formatBytes(_ bytes: Int, _ language: String) -> String {
    let units = language == "ru" ? ["Б", "КБ", "МБ", "ГБ", "ТБ"] : ["B", "KB", "MB", "GB", "TB"]
    var value = Double(max(0, bytes)), index = 0
    while value >= 1024 && index < units.count - 1 { value /= 1024; index += 1 }
    let number = index == 0 ? String(Int(value)) : String(format: "%.1f", value)
    return "\(language == "ru" ? number.replacingOccurrences(of: ".", with: ",") : number) \(units[index])"
}

@MainActor final class AppModel: ObservableObject {
    @Published var language = UserDefaults.standard.string(forKey: "language") ?? "ru" {
        didSet { UserDefaults.standard.set(language, forKey: "language") }
    }
    @Published var accounts: [Account] = []
    @Published var active: String? = nil
    @Published var shared: [String] = []
    @Published var session = "unknown"
    @Published var sessionMessage = LocalMessage()
    @Published var jobState = "idle"
    @Published var loginStatus = ""
    @Published var loginNeeds2FA = false
    @Published var loginMessage = LocalMessage()
    @Published var phones: [Phone] = []
    @Published var albums: [Album] = []
    @Published var message = LocalMessage()
    @Published var showingError = false
    @Published var plan: [String: Any] = [:]
    @Published var progress: [String: Any] = [:]
    @Published var scanned = 0
    @Published var isCountingPhase = false
    @Published var report: [String: Any] = [:]
    @Published var problems: [(String, String, LocalMessage)] = []
    @Published var ready = false
    @Published var speed: Double = 0
    private var lastSample: (Date, Int)?
    @Published var unfinished: [String: Any] = [:]
    @Published var showUnfinished = false
    var process: Process?
    var input: FileHandle?
    private var isQuitting = false
    private var buffer = Data()
    private let decoder: JSONDecoder = { let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d }()
    var running: Bool { ["counting", "downloading", "paused"].contains(jobState) }
    var current: Account? { accounts.first { $0.appleId == active } }
    var reportProblems: [(String, String, LocalMessage)] {
        var result: [(String, String, LocalMessage)] = []
        for (key, label) in [("errors", "Errors"), ("conflicts", "Conflicts"), ("compact_errors", "Compact copies")] {
            for row in report[key] as? [[Any]] ?? [] {
                if row.count == 2, let path = row[0] as? String, let reason = decode(LocalMessage.self, row[1]) {
                    result.append((path, label, reason))
                }
            }
        }
        return result
    }
    func t(_ key: String) -> String { tr(key, language) }
    func decode<T: Decodable>(_ type: T.Type, _ value: Any?) -> T? {
        guard let value = value, JSONSerialization.isValidJSONObject(value), let data = try? JSONSerialization.data(withJSONObject: value) else { return nil }
        return try? decoder.decode(type, from: data)
    }
    func start() {
        guard process == nil else { return }
        let task = Process()
        if let path = ProcessInfo.processInfo.environment["IPD_BRIDGE_EXECUTABLE"] {
            task.executableURL = URL(fileURLWithPath: path)
            task.arguments = ["-m", "ipd_app.macos_bridge"]
        } else if let root = Bundle.main.resourceURL {
            task.executableURL = root.appendingPathComponent("engine/ipd-bridge")
        }
        if let count = ProcessInfo.processInfo.environment["IPD_FAKE"] { task.arguments = (task.arguments ?? []) + ["--fake", count] }
        let toWorker = Pipe(), fromWorker = Pipe()
        task.standardInput = toWorker; task.standardOutput = fromWorker
        input = toWorker.fileHandleForWriting
        fromWorker.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.receive(data) }
        }
        task.terminationHandler = { [weak self] _ in DispatchQueue.main.async {
            guard let self = self else { return }; self.ready = false
            if self.isQuitting { NSApplication.shared.terminate(nil) }
            else { self.message = LocalMessage(ru: tr("The background service stopped.", "ru"), en: "The background service stopped."); self.showingError = true }
        } }
        do { try task.run(); process = task }
        catch { message = LocalMessage(ru: tr("Could not start the background service.", "ru"), en: "Could not start the background service."); showingError = true }
    }
    func send(_ action: String, _ fields: [String: Any] = [:]) {
        var object = fields; object["action"] = action
        guard let data = try? JSONSerialization.data(withJSONObject: object), let handle = input else { return }
        var line = data; line.append(10)
        try? handle.write(contentsOf: line)
    }
    func receive(_ data: Data) {
        buffer.append(data)
        while let index = buffer.firstIndex(of: 10) {
            let line = buffer.prefix(upTo: index); buffer.removeSubrange(...index)
            guard let value = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any], let event = value["event"] as? String else { continue }
            switch event {
            case "ready": ready = true
            case "accounts": accounts = decode([Account].self, value["accounts"]) ?? []; active = value["active"] as? String; shared = value["shared"] as? [String] ?? []
            case "session": session = value["state"] as? String ?? "unknown"; sessionMessage = decode(LocalMessage.self, value["message"]) ?? LocalMessage(); if session == "ok" { send("unfinished") }
            case "login":
                loginStatus = value["status"] as? String ?? "failed"
                if loginStatus == "needs_2fa" { loginNeeds2FA = true; phones = decode([Phone].self, value["phones"]) ?? [] }
                if loginStatus == "failed" { loginNeeds2FA = loginNeeds2FA && (value["pending"] as? Bool ?? false); loginMessage = decode(LocalMessage.self, value["message"]) ?? LocalMessage() }
                else { loginMessage = LocalMessage() }
            case "albums": albums = decode([Album].self, value["albums"]) ?? []; let m = decode(LocalMessage.self, value["message"]) ?? LocalMessage(); if !m.ru.isEmpty { message = m; showingError = true }
            case "job_state":
                let next = value["state"] as? String ?? "idle"
                if next == "counting" && !isCountingPhase { scanned = 0 }
                if next == "counting" { isCountingPhase = true }
                else if next != "paused" { isCountingPhase = false }
                jobState = next
                if jobState != "downloading" { lastSample = nil; speed = 0 }
            case "count_progress": scanned = value["scanned"] as? Int ?? 0
            case "plan": plan = value["plan"] as? [String: Any] ?? [:]
            case "progress":
                progress = value
                let now = Date(), bytes = value["done_bytes"] as? Int ?? 0
                if let (last, previous) = lastSample, jobState == "downloading" { let elapsed = now.timeIntervalSince(last); if elapsed > 0 { speed = Double(max(0, bytes - previous)) / elapsed } }
                lastSample = (now, bytes)
            case "problem": problems.append((value["path"] as? String ?? "", value["kind"] as? String ?? "", decode(LocalMessage.self, value["message"]) ?? LocalMessage()))
            case "unfinished": if let job = value["job"] as? [String: Any] { unfinished = job; showUnfinished = true }
            case "finished": report = value["report"] as? [String: Any] ?? [:]; let m = decode(LocalMessage.self, value["message"]) ?? LocalMessage(); if !m.ru.isEmpty { message = m; showingError = true }; notify(report.isEmpty ? "Error" : ((report["stopped_reason"] as? [String: String])?["ru"]?.isEmpty == false ? "Job stopped" : "Job complete"))
            case "error": message = decode(LocalMessage.self, value["message"]) ?? LocalMessage(); showingError = true
            default: break
            }
        }
    }
    func notify(_ key: String) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { allowed, _ in
            guard allowed else { return }
            let content = UNMutableNotificationContent(); content.title = tr(key, UserDefaults.standard.string(forKey: "language") ?? "ru"); content.sound = .default
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        }
    }
    func save(_ account: Account) {
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        guard let data = try? encoder.encode(account), let values = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        var updated = values
        if account.compactLongSide == nil { updated["compact_long_side"] = NSNull() }
        if account.albums == nil { updated["albums"] = NSNull() }
        send("settings", ["values": updated])
    }
    func quit() {
        if running {
            let alert = NSAlert(); alert.messageText = t("A job is running. Stop it and quit?")
            alert.addButton(withTitle: t("Stop and quit")); alert.addButton(withTitle: t("Cancel"))
            guard alert.runModal() == .alertFirstButtonReturn else { return }
        }
        guard process != nil else { NSApplication.shared.terminate(nil); return }
        isQuitting = true; jobState = "quitting"; send("quit")
    }
}

@main struct DownloaderApp: App {
    @StateObject var model = AppModel()
    var body: some Scene {
        WindowGroup("iCloud Photo Downloader", id: "main") { MainView(model: model).onAppear { model.start() } }
            .windowStyle(.titleBar)
            .commands { CommandGroup(replacing: .appTermination) { Button(model.t("Quit")) { model.quit() }.keyboardShortcut("q") } }
        MenuBarExtra("iCloud Photo Downloader", systemImage: "icloud.and.arrow.down") {
            MenuBarContent(model: model)
        }
    }
}

struct MenuBarContent: View {
    @ObservedObject var model: AppModel
    @Environment(\.openWindow) var openWindow
    var body: some View {
        Button(model.t("Open")) { openWindow(id: "main"); NSApp.activate(ignoringOtherApps: true) }
        Text(model.t(model.running ? "Downloading" : "Waiting"))
        Button(model.t(model.jobState == "paused" ? "Resume" : "Pause")) { model.send(model.jobState == "paused" ? "resume" : "pause") }.disabled(!model.running)
        Button(model.t("Stop")) { model.send("stop") }.disabled(!model.running)
        Divider()
        Button(model.t("Quit")) { model.quit() }
    }
}

struct MainView: View {
    @ObservedObject var model: AppModel
    @LegacyState(wrappedValue: false) private var showLogin: Bool
    @LegacyState(wrappedValue: false) private var showSettings: Bool
    @LegacyState(wrappedValue: false) private var showDetails: Bool
    @LegacyState(wrappedValue: false) private var showLogs: Bool
    @LegacyState(wrappedValue: false) private var confirmRemove: Bool
    @LegacyState(wrappedValue: false) private var confirmSignOut: Bool
    @LegacyState(wrappedValue: true) private var allTime: Bool
    @LegacyState(wrappedValue: Calendar.current.date(byAdding: .year, value: -1, to: Date()) ?? Date()) private var from: Date
    @LegacyState(wrappedValue: Date()) private var to: Date
    func dateString(_ date: Date) -> String { let f = DateFormatter(); f.calendar = Calendar(identifier: .gregorian); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f.string(from: date) }
    func integer(_ object: [String: Any], _ key: String) -> Int { object[key] as? Int ?? 0 }
    func begin(_ action: String) {
        guard model.current?.rootDir.isEmpty == false else { showSettings = true; return }
        model.plan = [:]
        if action == "start" { model.problems = []; model.report = [:]; model.progress = [:] }
        model.send(action, allTime ? [:] : ["from": dateString(from), "to": dateString(to)])
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Image(systemName: "icloud.and.arrow.down.fill").font(.largeTitle).foregroundStyle(.blue)
                VStack(alignment: .leading) { Text("iCloud Photo Downloader").font(.title2.bold()); Text(model.t("Downloads")).foregroundStyle(.secondary) }
                Spacer()
                Picker(model.t("Language"), selection: $model.language) { Text("Русский").tag("ru"); Text("English").tag("en") }.frame(width: 180)
            }
            GroupBox(model.t("Accounts")) {
                HStack {
                    Picker(model.t("Accounts"), selection: Binding(get: { model.active ?? "" }, set: { model.send("activate", ["apple_id": $0]) })) {
                        if model.accounts.isEmpty { Text(model.t("No account selected")).tag("") }
                        ForEach(model.accounts) { Text($0.appleId).tag($0.appleId) }
                    }.labelsHidden().frame(minWidth: 180)
                    Button(model.t("Add account")) { model.loginStatus = ""; model.loginNeeds2FA = false; model.loginMessage = LocalMessage(); showLogin = true }
                    if model.current != nil {
                        Button(model.t("Sign in")) { model.loginStatus = ""; model.loginNeeds2FA = false; model.loginMessage = LocalMessage(); showLogin = true }
                        Button(model.t("Settings")) { showSettings = true }
                        Menu { Button(model.t("Sign out")) { confirmSignOut = true }; Button(model.t("Remove account"), role: .destructive) { confirmRemove = true } } label: { Image(systemName: "ellipsis.circle") }
                    }
                    Spacer()
                }.disabled(model.running)
                HStack { Circle().fill(model.session == "ok" ? .green : .orange).frame(width: 8, height: 8); Text(sessionText).font(.caption).foregroundStyle(.secondary); Spacer() }
                if let account = model.current {
                    HStack {
                        Text("\(model.t("Download folder")): \(account.rootDir.isEmpty ? model.t("No folder selected") : account.rootDir)")
                            .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
                        if account.rootDir.isEmpty { Button(model.t("Choose folder")) { showSettings = true }.disabled(model.running) }
                        Spacer()
                    }
                }
            }
            GroupBox(model.t("Period")) {
                VStack(alignment: .leading) {
                    Toggle(model.t("All time"), isOn: $allTime)
                    if !allTime {
                        HStack {
                            Button(model.t("This year")) { let c = Calendar.current; from = c.date(from: c.dateComponents([.year], from: Date())) ?? Date(); to = Date() }
                            Button(model.t("Last year")) { let c = Calendar.current; let start = c.date(from: c.dateComponents([.year], from: Date())) ?? Date(); from = c.date(byAdding: .year, value: -1, to: start) ?? start; to = c.date(byAdding: .day, value: -1, to: start) ?? start }
                            Button(model.t("Last 30 days")) { to = Date(); from = Calendar.current.date(byAdding: .day, value: -29, to: to) ?? to }
                        }
                        HStack { DatePicker(model.t("From"), selection: $from, displayedComponents: .date); DatePicker(model.t("To"), selection: $to, displayedComponents: .date) }
                        Text(model.t("Both dates are inclusive.")).font(.caption).foregroundStyle(.secondary)
                    }
                    HStack {
                        Button(model.t("Preview")) { begin("preview") }.disabled(model.running || !model.ready || model.current == nil)
                        Button(model.t("Start")) { begin("start") }.disabled(model.running || !model.ready || model.current == nil)
                        Button(model.t(model.jobState == "paused" ? "Resume" : "Pause")) { model.send(model.jobState == "paused" ? "resume" : "pause") }.disabled(!model.running)
                        Button(model.t("Stop")) { model.send("stop") }.disabled(!model.running)
                        Spacer()
                    }
                }.padding(.vertical, 3)
            }
            GroupBox(model.t("Progress")) {
                VStack(alignment: .leading, spacing: 7) {
                    HStack {
                        Text(model.t(stateText)).bold(); Spacer()
                        if model.isCountingPhase && model.running {
                            Text("\(model.t("Items checked")): \(model.scanned)")
                        } else {
                            Text("\(model.t("Files")): \(integer(model.progress, "done")) / \(integer(model.progress, "total"))")
                        }
                    }
                    if model.isCountingPhase && model.running {
                        ProgressView().controlSize(.small)
                        Text(model.t("Checking a large library can take time. The counter updates as items are checked."))
                            .font(.caption).foregroundStyle(.secondary)
                    } else {
                        ProgressView(value: Double(integer(model.progress, "done")), total: Double(max(1, integer(model.progress, "total"))))
                        Text("\(model.t("Size")): \(formatBytes(integer(model.progress, "done_bytes"), model.language)) / \(formatBytes(integer(model.progress, "total_bytes"), model.language))").font(.caption)
                    }
                    if model.speed > 0 { let left = max(0, integer(model.progress, "total_bytes") - integer(model.progress, "done_bytes")); Text("\(model.t("Speed")): \(formatBytes(Int(model.speed), model.language))/\(model.language == "ru" ? "с" : "s") · \(model.t("Remaining")): \(Int(Double(left) / model.speed)) \(model.language == "ru" ? "с" : "s")").font(.caption) }
                    if let current = model.progress["current"] as? String, !current.isEmpty { Text("\(model.t("Current file")): \(current)").font(.caption).lineLimit(1) }
                    if !model.plan.isEmpty { Text("\(model.t("Download plan")): \(model.t("In period")) \(integer(model.plan, "files_in_period")) · \(model.t("Already present")) \(integer(model.plan, "files_present")) · \(model.t("To download")) \(integer(model.plan, "files_to_download")) · \(model.t("Compact copies")) \(integer(model.plan, "compact_to_make"))").font(.caption) }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            GroupBox(model.t("Last run")) {
                HStack { if model.report.isEmpty { Text(model.t("No jobs yet")) } else { Text("\(model.t("Downloaded")): \(integer(model.report, "downloaded")) · \(model.t("Skipped")): \(integer(model.report, "skipped")) · \(model.t("Errors")): \((model.report["errors"] as? [Any])?.count ?? 0) · \(model.t("Conflicts")): \((model.report["conflicts"] as? [Any])?.count ?? 0)"); Button(model.t("Show details")) { showDetails = true } }; Spacer() }
            }
            HStack { Button(model.t("Open folder")) { if let path = model.current?.rootDir, !path.isEmpty { NSWorkspace.shared.open(URL(fileURLWithPath: path)) } }.disabled(model.current?.rootDir.isEmpty != false); Button(model.t("View logs")) { showLogs = true }; Spacer() }
        }.padding(24).frame(minWidth: 720, minHeight: 570)
        .sheet(isPresented: $showLogin) { LoginView(model: model, isPresented: $showLogin) }
        .sheet(isPresented: $showSettings) { if let current = model.current { SettingsView(model: model, account: current, isPresented: $showSettings) } }
        .sheet(isPresented: $showDetails) { DetailsView(model: model) }
        .sheet(isPresented: $showLogs) { LogsView(model: model) }
        .alert(model.t("Error"), isPresented: $model.showingError) { Button("OK") {} } message: { Text(model.message.text(model.language)) }
        .confirmationDialog(model.t("Remove this account? Downloaded files will remain."), isPresented: $confirmRemove) { Button(model.t("Remove"), role: .destructive) { if let id = model.active { model.send("remove", ["apple_id": id]) } } }
        .confirmationDialog(model.t("Sign out of this account?"), isPresented: $confirmSignOut) { Button(model.t("Sign out"), role: .destructive) { if let id = model.active { model.send("sign_out", ["apple_id": id]) } } }
        .confirmationDialog(model.t("Resume unfinished job?"), isPresented: $model.showUnfinished) {
            Button(model.t("Resume")) {
                var period: [String: Any] = [:]
                if let date = model.unfinished["date_from"] as? String { period["from"] = date }
                if let date = model.unfinished["date_to"] as? String { period["to"] = date }
                model.send("start", period)
            }
            Button(model.t("Cancel"), role: .cancel) {}
        }
        .onChange(of: showLogin) { open in
            if !open && model.loginStatus == "ok" && model.current?.rootDir.isEmpty == true {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { showSettings = true }
            }
        }
    }
    var stateText: String { switch model.jobState { case "counting": return "Counting"; case "downloading": return "Downloading"; case "paused": return "Paused"; case "error": return "Error"; default: return "Waiting" } }
    var sessionText: String { switch model.session { case "checking": return model.t("Checking session"); case "ok": return model.t("Session active"); case "expired": return model.t("Sign-in required"); case "error": return model.sessionMessage.text(model.language); default: return model.t("Session unchecked") } }
}

struct LoginView: View {
    @ObservedObject var model: AppModel
    @Binding var isPresented: Bool
    @LegacyState(wrappedValue: "") var appleId: String
    @LegacyState(wrappedValue: "") var password: String
    @LegacyState(wrappedValue: "") var code: String
    @LegacyState(wrappedValue: nil) var phone: Int?
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(model.t("Sign in")).font(.title2.bold())
            if model.loginNeeds2FA {
                Text(model.t("Enter the six-digit code from your Apple device."))
                TextField(model.t(phone == nil ? "Verification code" : "SMS code"), text: $code)
                HStack { Button(model.t("Confirm")) { if let id = phone { model.send("sms_code", ["phone_id": id, "code": code]) } else { model.send("code", ["code": code]) }; code = "" }.disabled(code.count != 6)
                    ForEach(model.phones) { item in Button("\(model.t("Send SMS")) \(item.maskedNumber)") { phone = item.id; model.send("request_sms", ["phone_id": item.id]) } }
                }
            } else {
                TextField(model.t("Apple ID"), text: $appleId)
                SecureField(model.t("Password"), text: $password)
                Text(model.t("iCloud web access must be enabled. Advanced Data Protection and security keys are not supported.")).font(.caption).foregroundStyle(.secondary)
                Button(model.t("Sign in")) { model.send("login", ["apple_id": appleId, "password": password.isEmpty ? NSNull() : password as Any]); password = "" }.disabled(appleId.isEmpty)
            }
            if !model.loginMessage.ru.isEmpty { Text(model.loginMessage.text(model.language)).foregroundStyle(.red) }
            HStack { Spacer(); Button(model.t("Cancel")) { model.send("cancel_login"); password = ""; isPresented = false } }
        }.padding(24).frame(width: 480)
        .onAppear { appleId = model.active ?? "" }
        .onChange(of: model.loginStatus) { status in if status == "ok" { isPresented = false } }
    }
}

struct SettingsView: View {
    enum Section: String, CaseIterable {
        case folder, media, compact, downloads

        var title: String {
            switch self {
            case .folder: return "Folder"
            case .media: return "Media"
            case .compact: return "Compact"
            case .downloads: return "Downloads"
            }
        }
    }

    @ObservedObject var model: AppModel
    @LegacyState(wrappedValue: Account(appleId: "")) var account: Account
    init(model: AppModel, account: Account, isPresented: Binding<Bool>) { self.model = model; self._account = State(wrappedValue: account); self._isPresented = isPresented }
    @Binding var isPresented: Bool
    @LegacyState(wrappedValue: false) var useAlbums: Bool
    @LegacyState(wrappedValue: []) var selected: Set<String>
    @LegacyState(wrappedValue: false) var invalid: Bool
    @LegacyState(wrappedValue: Section.folder) var section: Section
    var body: some View {
        VStack(alignment: .leading) {
            Text("\(model.t("Settings")): \(account.appleId)").font(.title2.bold())
            Picker(model.t("Settings"), selection: $section) {
                ForEach(Section.allCases, id: \.self) { item in
                    Text(model.t(item.title)).tag(item)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.top, 8)

            Group {
                switch section {
                case .folder:
                VStack(alignment: .leading, spacing: 12) {
                    Text(model.t("Choose where to save photos and videos downloaded from iCloud.")).font(.headline)
                    Text(model.t("The app creates folders by year and month, with originals in Full size and JPEG copies in Compact.")).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    Text(account.rootDir.isEmpty ? model.t("No folder selected") : account.rootDir).textSelection(.enabled)
                    Button(model.t("Choose folder")) { let panel = NSOpenPanel(); panel.title = model.t("iCloud photo download folder"); panel.message = model.t("Choose where to save photos and videos downloaded from iCloud."); panel.prompt = model.t("Choose"); panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true; if panel.runModal() == .OK, let url = panel.url { account.rootDir = url.path } }
                    if model.accounts.contains(where: { $0.appleId != account.appleId && !$0.rootDir.isEmpty && $0.rootDir == account.rootDir }) { Text(model.t("Shared folder warning")).foregroundStyle(.orange) }
                    Spacer()
                }
                case .media:
                VStack(alignment: .leading) {
                    Toggle(model.t("Photos"), isOn: $account.photos); Toggle(model.t("Videos"), isOn: $account.videos)
                    Toggle(model.t("Include Live Photo video"), isOn: $account.liveVideo); Toggle(model.t("Include edited versions"), isOn: $account.edited)
                    Toggle(model.t("Selected albums"), isOn: $useAlbums)
                    if useAlbums { Button(model.t("Load albums")) { model.send("albums") }; ScrollView { ForEach(model.albums) { album in Toggle(album.name, isOn: Binding(get: { selected.contains(album.id) }, set: { if $0 { selected.insert(album.id) } else { selected.remove(album.id) } })) } }.frame(maxHeight: 140) }
                    Text(model.t("Hidden, recently deleted and shared albums are excluded.")).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                }
                case .compact:
                VStack(alignment: .leading) {
                    Toggle(model.t("Create JPEG copies"), isOn: $account.compactEnabled)
                    Picker(model.t("Long edge"), selection: Binding(get: { account.compactLongSide ?? 0 }, set: { account.compactLongSide = $0 == 0 ? nil : $0 })) { Text(model.t("Original size")).tag(0); Text("4096 px").tag(4096); Text("2048 px").tag(2048); Text("1600 px").tag(1600) }
                    Stepper("\(model.t("JPEG quality")): \(account.compactQuality)", value: $account.compactQuality, in: 60...95)
                    Spacer()
                }
                case .downloads:
                VStack(alignment: .leading) {
                    Stepper("\(model.t("Parallel downloads")): \(account.concurrency)", value: $account.concurrency, in: 1...8)
                    HStack { Text(model.t("Minimum free space (GB)")); TextField("GB", value: $account.minFreeGb, format: .number).frame(width: 80) }
                    Toggle(model.t("Restore manually deleted files"), isOn: $account.restoreDeleted)
                    Spacer()
                }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(.top, 12)
            HStack { Spacer(); Button(model.t("Cancel")) { isPresented = false }; Button(model.t("Save")) { if useAlbums && selected.isEmpty { invalid = true; return }; account.albums = useAlbums ? Array(selected).sorted() : nil; model.save(account); isPresented = false }.keyboardShortcut(.defaultAction) }
        }.padding(24).frame(width: 600, height: 460)
        .onAppear { selected = Set(account.albums ?? []); useAlbums = account.albums != nil }
        .alert(model.t("Error"), isPresented: $invalid) { Button("OK") {} } message: { Text(model.t("Select at least one album.")) }
    }
}

struct DetailsView: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    var body: some View {
        VStack(alignment: .leading) { Text(model.t("Details")).font(.title2.bold()); List {
            if let reason = model.decode(LocalMessage.self, model.report["stopped_reason"]), !reason.ru.isEmpty { Text(reason.text(model.language)) }
            ForEach(Array(model.reportProblems.enumerated()), id: \.offset) { _, item in VStack(alignment: .leading) { Text(item.0).textSelection(.enabled); Text("\(model.t(item.1)): \(item.2.text(model.language))").font(.caption).foregroundStyle(.secondary) } }
        }; HStack { Spacer(); Button(model.t("Close")) { dismiss() } } }.padding(24).frame(width: 620, height: 400)
    }
}
struct LogsView: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) var dismiss
    @LegacyState(wrappedValue: "") var content: String
    var folder: URL { FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/iCloudPhotoDownloader") }
    var body: some View {
        VStack(alignment: .leading) { Text(model.t("Application log")).font(.title2.bold()); ScrollView { Text(content).font(.system(.caption, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }; HStack { Button(model.t("Refresh")) { load() }; Button(model.t("Open log folder")) { NSWorkspace.shared.open(folder) }; Spacer(); Button(model.t("Close")) { dismiss() } } }.padding(24).frame(width: 720, height: 460).onAppear { load() }
    }
    func load() { content = (try? String(contentsOf: folder.appendingPathComponent("app.log"), encoding: .utf8)) ?? "" }
}
