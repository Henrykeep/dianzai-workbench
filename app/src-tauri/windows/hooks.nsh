; 芯台安装钩子（Tauri v2 NSIS installerHooks）
; - 文件名 / 安装目录用 ASCII 的 productName（XinTai）；开始菜单只留一个中文名「芯台」快捷方式
; - 发现旧版「电赛工作台」（旧 productName）：问是否卸载（默认“是”；/S 静默安装自动取默认）→ 静默跑旧卸载器，只删程序文件；
;   用户工程在 %USERPROFILE%\.dzbench（$DZBENCH_HOME），卸载器从不碰它；装完提示「你的工程已保留」
Var DzOldUninst
Var DzOldDir
Var DzOldRemoved

!macro NSIS_HOOK_PREINSTALL
  StrCpy $DzOldRemoved 0
  ReadRegStr $DzOldUninst HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\电赛工作台" "UninstallString"
  ReadRegStr $DzOldDir HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\电赛工作台" "InstallLocation"
  ${If} $DzOldDir == ""
    ${If} ${FileExists} "$LOCALAPPDATA\电赛工作台\uninstall.exe"
      StrCpy $DzOldDir "$LOCALAPPDATA\电赛工作台"
    ${EndIf}
  ${EndIf}
  ${If} $DzOldDir != ""
    StrCpy $DzOldUninst "$DzOldDir\uninstall.exe"
  ${EndIf}
  ${If} $DzOldUninst != ""
  ${AndIf} ${FileExists} "$DzOldUninst"
    DetailPrint "芯台：检测到旧版电赛工作台（$DzOldDir）"
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON1 "检测到旧版电赛工作台，是否卸载？$\r$\n（只删除旧程序文件；你的工程在 %USERPROFILE%\.dzbench，不会动）" /SD IDYES IDNO dz_keep_old
      DetailPrint "芯台：静默卸载旧版（只删程序文件，不碰 .dzbench）"
      ExecWait '"$DzOldUninst" /S _?=$DzOldDir' $0
      Delete "$DzOldUninst"
      RMDir "$DzOldDir"
      Delete "$SMPROGRAMS\电赛工作台.lnk"
      Delete "$DESKTOP\电赛工作台.lnk"
      DetailPrint "芯台：旧版卸载器退出码 $0"
      StrCpy $DzOldRemoved 1
      Goto dz_old_done
    dz_keep_old:
      DetailPrint "芯台：用户选择保留旧版电赛工作台"
    dz_old_done:
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Tauri 在这之前已建好 $SMPROGRAMS\${PRODUCTNAME}.lnk：改名成「芯台」，保证只有一个
  ${If} ${FileExists} "$SMPROGRAMS\${PRODUCTNAME}.lnk"
    Delete "$SMPROGRAMS\芯台.lnk"
    Rename "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$SMPROGRAMS\芯台.lnk"
    DetailPrint "芯台：开始菜单快捷方式 = 芯台.lnk"
  ${EndIf}
  ${If} $DzOldRemoved = 1
    DetailPrint "芯台：你的工程已保留（%USERPROFILE%\.dzbench）"
    MessageBox MB_OK|MB_ICONINFORMATION "你的工程已保留" /SD IDOK
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  Delete "$SMPROGRAMS\芯台.lnk"
!macroend
