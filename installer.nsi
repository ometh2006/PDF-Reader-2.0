; ============================================================
; LitePDF NSIS Installer Script
; Creates: installer, Start Menu shortcut, .pdf file association
; ============================================================

Unicode True

!define APP_NAME        "LitePDF"
; APP_VERSION can be overridden from the command line: /DAPP_VERSION=x.y.z
!ifndef APP_VERSION
  !define APP_VERSION   "2.0.0"
!endif
!define APP_EXE         "LitePDF.exe"
!define APP_PUBLISHER   "LitePDF Project"
!define APP_URL         "https://github.com/${GITHUB_REPO}"
!define INSTALL_DIR     "$PROGRAMFILES64\${APP_NAME}"
!define REG_UNINST      "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
!define REG_CLASSES     "Software\Classes"

; ── Metadata ──────────────────────────────────────────────────────────────────
Name              "${APP_NAME} ${APP_VERSION}"
OutFile           "LitePDF-Setup-${APP_VERSION}.exe"
InstallDir        "${INSTALL_DIR}"
InstallDirRegKey  HKLM "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel admin
SetCompressor     /SOLID lzma
BrandingText      "${APP_NAME} ${APP_VERSION} Installer"

; ── Modern UI ─────────────────────────────────────────────────────────────────
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON          "icon.ico"
!define MUI_UNICON        "icon.ico"
!define MUI_WELCOMEPAGE_TITLE  "Welcome to ${APP_NAME} Setup"
!define MUI_WELCOMEPAGE_TEXT   \
    "This wizard will install ${APP_NAME} ${APP_VERSION} on your computer.$\r$\n$\r$\n\
Lightweight PDF reader & editor — no Java, no browser engine.$\r$\n$\r$\n\
Click Next to continue."

!define MUI_FINISHPAGE_RUN         "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT    "Launch ${APP_NAME} now"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ── Installer sections ────────────────────────────────────────────────────────
Section "Main Application" SEC_MAIN
    SectionIn RO   ; required

    SetOutPath "$INSTDIR"
    File "dist\${APP_EXE}"

    ; ── Registry: uninstall entry ──────────────────────────────────────────
    WriteRegStr   HKLM "${REG_UNINST}" "DisplayName"      "${APP_NAME}"
    WriteRegStr   HKLM "${REG_UNINST}" "DisplayVersion"   "${APP_VERSION}"
    WriteRegStr   HKLM "${REG_UNINST}" "Publisher"        "${APP_PUBLISHER}"
    WriteRegStr   HKLM "${REG_UNINST}" "URLInfoAbout"     "${APP_URL}"
    WriteRegStr   HKLM "${REG_UNINST}" "InstallLocation"  "$INSTDIR"
    WriteRegStr   HKLM "${REG_UNINST}" "UninstallString"  '"$INSTDIR\uninstall.exe"'
    WriteRegStr   HKLM "${REG_UNINST}" "DisplayIcon"      "$INSTDIR\${APP_EXE}"
    WriteRegDWORD HKLM "${REG_UNINST}" "NoModify"         1
    WriteRegDWORD HKLM "${REG_UNINST}" "NoRepair"         1

    ; ── Estimated install size ─────────────────────────────────────────────
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "${REG_UNINST}" "EstimatedSize" "$0"

    ; ── File association: .pdf → LitePDF ──────────────────────────────────
    ; 1. Register the ProgID
    WriteRegStr HKLM "${REG_CLASSES}\LitePDF.Document"                        "" "PDF Document"
    WriteRegStr HKLM "${REG_CLASSES}\LitePDF.Document\DefaultIcon"            "" "$INSTDIR\${APP_EXE},0"
    WriteRegStr HKLM "${REG_CLASSES}\LitePDF.Document\shell\open\command"     "" '"$INSTDIR\${APP_EXE}" "%1"'
    WriteRegStr HKLM "${REG_CLASSES}\LitePDF.Document\shell\open"             "FriendlyAppName" "${APP_NAME}"

    ; 2. Associate .pdf extension (as default — user can change in Settings)
    WriteRegStr HKLM "${REG_CLASSES}\.pdf"                   "" "LitePDF.Document"
    WriteRegStr HKLM "${REG_CLASSES}\.pdf\OpenWithProgids"   "LitePDF.Document" ""

    ; 3. Register in OpenWith list
    WriteRegStr HKLM "Software\${APP_NAME}"                  "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "${REG_CLASSES}\Applications\${APP_EXE}\shell\open\command" \
                     "" '"$INSTDIR\${APP_EXE}" "%1"'

    ; Notify shell of association change
    System::Call 'Shell32::SHChangeNotify(i 0x08000000, i 0, i 0, i 0)'

    ; ── Start Menu shortcut ────────────────────────────────────────────────
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortcut  "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" \
                    "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0 \
                    SW_SHOWNORMAL "" "Open PDFs with ${APP_NAME}"
    CreateShortcut  "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" \
                    "$INSTDIR\uninstall.exe"

    ; ── Desktop shortcut (optional — comment out to remove) ───────────────
    CreateShortcut  "$DESKTOP\${APP_NAME}.lnk" \
                    "$INSTDIR\${APP_EXE}" "" "$INSTDIR\${APP_EXE}" 0

    ; ── Write uninstaller ─────────────────────────────────────────────────
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; ── Uninstaller ───────────────────────────────────────────────────────────────
Section "Uninstall"
    Delete "$INSTDIR\${APP_EXE}"
    Delete "$INSTDIR\uninstall.exe"
    RMDir  "$INSTDIR"

    ; Remove Start Menu
    Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk"
    RMDir  "$SMPROGRAMS\${APP_NAME}"

    ; Remove Desktop shortcut
    Delete "$DESKTOP\${APP_NAME}.lnk"

    ; Remove registry entries
    DeleteRegKey HKLM "${REG_UNINST}"
    DeleteRegKey HKLM "Software\${APP_NAME}"
    DeleteRegKey HKLM "${REG_CLASSES}\LitePDF.Document"

    ; Remove .pdf association only if we set it
    ReadRegStr $0 HKLM "${REG_CLASSES}\.pdf" ""
    StrCmp $0 "LitePDF.Document" 0 +2
        DeleteRegValue HKLM "${REG_CLASSES}\.pdf" ""

    DeleteRegValue HKLM "${REG_CLASSES}\.pdf\OpenWithProgids" "LitePDF.Document"
    DeleteRegKey   HKLM "${REG_CLASSES}\Applications\${APP_EXE}"

    System::Call 'Shell32::SHChangeNotify(i 0x08000000, i 0, i 0, i 0)'
SectionEnd
