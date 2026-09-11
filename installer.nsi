; 创建时间: 2026-09-11
; 功能: Codex Usage Watch 安装包脚本(NSIS 3.x)
; 目的: 将 dist/CodexUsageWatch.exe 打包为用户级安装程序:
;       安装到 LocalAppData(免管理员), 可选桌面快捷方式与开机自启,
;       写入卸载信息, 供 GitHub Releases 发布下载。
; 用法: makensis /DAPP_VERSION=1.0.0 installer.nsi  (仓库根目录执行)

Unicode true

!ifndef APP_VERSION
  !define APP_VERSION "1.0.0"
!endif

!define APP_NAME "Codex Usage Watch"
!define APP_EXE "CodexUsageWatch.exe"
!define REG_UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\CodexUsageWatch"
!define REG_RUN "Software\Microsoft\Windows\CurrentVersion\Run"

!include "MUI2.nsh"

Name "${APP_NAME} ${APP_VERSION}"
OutFile "installer\CodexUsageWatch-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\CodexUsageWatch"
RequestExecutionLevel user
SetCompressor /SOLID lzma

!define MUI_ICON "assets\icon.ico"
!define MUI_UNICON "assets\icon.ico"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${APP_NAME}"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Section "主程序 (必需)" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"
  File "/oname=${APP_EXE}" "dist\CodexUsageWatch.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; 控制面板「应用和功能」卸载信息(HKCU, 用户级)
  WriteRegStr HKCU "${REG_UNINST}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${REG_UNINST}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${REG_UNINST}" "Publisher" "codexUsageWatch"
  WriteRegStr HKCU "${REG_UNINST}" "DisplayIcon" "$INSTDIR\${APP_EXE}"
  WriteRegStr HKCU "${REG_UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${REG_UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${REG_UNINST}" "NoRepair" 1

  ; 开始菜单
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "桌面快捷方式" SEC_DESKTOP
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}"
SectionEnd

Section /o "开机自动启动" SEC_AUTORUN
  WriteRegStr HKCU "${REG_RUN}" "CodexUsageWatch" '"$INSTDIR\${APP_EXE}"'
SectionEnd

Section "Uninstall"
  ; 结束正在运行的实例, 避免删除失败
  nsExec::Exec 'taskkill /F /IM ${APP_EXE}'
  Sleep 500

  Delete "$INSTDIR\${APP_EXE}"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\config.json"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${APP_NAME}\卸载 ${APP_NAME}.lnk"
  RMDir "$SMPROGRAMS\${APP_NAME}"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  DeleteRegKey HKCU "${REG_UNINST}"
  DeleteRegValue HKCU "${REG_RUN}" "CodexUsageWatch"
SectionEnd
