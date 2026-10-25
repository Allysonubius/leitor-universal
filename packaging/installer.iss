; Instalador do Leitor Universal (Inno Setup 6).
; Uso: iscc /DAppVersion=1.2.3 packaging\installer.iss
; Instala por usuário (sem pedir administrador), o que permite a atualização automática.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Leitor Universal"
#define AppExe "LeitorUniversal.exe"
#define ProgId "LeitorUniversal.Livro"

[Setup]
AppId={{FDF7806C-E4D9-4C57-972E-07E7E891319F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Allyson de Oliveira Brandão
AppPublisherURL=https://github.com/Allysonubius/leitor-universal
AppUpdatesURL=https://github.com/Allysonubius/leitor-universal/releases
DefaultDirName={localappdata}\Programs\LeitorUniversal
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=LeitorUniversal-{#AppVersion}-setup
SetupIconFile=icone.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[InstallDelete]
; Remove arquivos da versão anterior para evitar bibliotecas órfãs.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\LeitorUniversal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Tipo de arquivo "Livro" e entrada em "Abrir com" (não altera o programa padrão do usuário).
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "Livro ({#AppName})"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
#define Assoc(Ext) \
  "Root: HKA; Subkey: ""Software\Classes\" + Ext + "\OpenWithProgids""; ValueType: string; ValueName: """ + ProgId + """; ValueData: """"; Flags: uninsdeletevalue" + NewLine + \
  "Root: HKA; Subkey: ""Software\Classes\Applications\" + AppExe + "\SupportedTypes""; ValueType: string; ValueName: """ + Ext + """; ValueData: """""
#emit Assoc(".pdf")
#emit Assoc(".epub")
#emit Assoc(".mobi")
#emit Assoc(".azw")
#emit Assoc(".azw3")
#emit Assoc(".prc")
#emit Assoc(".fb2")
#emit Assoc(".fbz")
#emit Assoc(".xps")
#emit Assoc(".oxps")
#emit Assoc(".cbz")
#emit Assoc(".cbr")
#emit Assoc(".txt")
#emit Assoc(".md")
#emit Assoc(".rtf")
#emit Assoc(".docx")
#emit Assoc(".odt")

[Run]
; Executado também na instalação silenciosa (atualização automática), reabrindo o app.
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall
