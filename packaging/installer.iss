; Inno Setup script. Built by build.ps1:
;   ISCC.exe /DAppVersion=0.1.0 packaging\installer.iss
; Result: dist\iCloudPhotoDownloader-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Folder produced by PyInstaller; the only thing the installer packs.
#ifndef SourceDir
  #define SourceDir "..\dist\iCloudPhotoDownloader"
#endif
#define AppName "iCloud Photo Downloader"
#define AppExe "iCloudPhotoDownloader.exe"
#define DataDirName "iCloudPhotoDownloader"

[Setup]
; Never change AppId: it is how an update finds the previous installation.
AppId={{6F0B6C1E-7C1B-4E0B-9E55-2B7C7A1D4F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
; Per-user installation: no administrator rights, no UAC prompt.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#DataDirName}
DisableDirPage=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
SetupIconFile=icon.ico
OutputDir=..\dist
OutputBaseFilename=iCloudPhotoDownloader-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; An update over a running copy: ask to close it instead of failing on locked files.
CloseApplications=yes
RestartApplications=no

; The installer speaks the language of Windows when it has it, otherwise English.
; Inno Setup ships no Chinese messages, so on a Chinese Windows the installer is in
; English; the program itself still starts in Chinese.
ShowLanguageDialog=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Python may leave compiled caches next to the program files.
Type: filesandordirs; Name: "{app}\_internal"

[CustomMessages]
english.RemoveSettings=Also remove the program's settings, saved passwords and iCloud sign-in data?%n%nDownloaded photos and videos stay where they are in any case.
spanish.RemoveSettings=¿Eliminar también los ajustes del programa, las contraseñas guardadas y los datos de inicio de sesión de iCloud?%n%nLas fotos y los vídeos descargados se quedarán donde están en cualquier caso.
brazilianportuguese.RemoveSettings=Remover também os ajustes do programa, as senhas salvas e os dados de início de sessão do iCloud?%n%nAs fotos e os vídeos baixados continuarão onde estão de qualquer forma.
japanese.RemoveSettings=プログラムの設定、保存されたパスワード、iCloud のサインイン情報も削除しますか？%n%nダウンロード済みの写真とビデオは、いずれの場合もそのまま残ります。
russian.RemoveSettings=Удалить также настройки программы, сохранённые пароли и данные входа в iCloud?%n%nСкачанные фото и видео в любом случае останутся на месте.

[Code]
// The uninstaller removes the program only. Settings, sessions, sync state and
// logs live in the user's profile and are removed only if the user says so.
// Downloaded photos are never touched: the uninstaller does not even know where they are.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    // In a silent uninstall nobody can answer, so the safe answer (keep) is taken.
    if SuppressibleMsgBox(ExpandConstant('{cm:RemoveSettings}'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
    begin
      // Passwords are in Windows Credential Manager; only the program can remove them,
      // and it must do so before its own files are gone.
      Exec(ExpandConstant('{app}\{#AppExe}'), 'forget-credentials', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      DelTree(ExpandConstant('{userappdata}\{#DataDirName}'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\{#DataDirName}'), True, True, True);
    end;
  end;
end;
