; CI 安装冒烟用：模拟旧版「电赛工作台」（当前用户安装，带真实 uninstall.exe，支持 /S 与 _?=）
Unicode true
Name "电赛工作台"
OutFile "old-setup.exe"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\电赛工作台"
Section
  SetOutPath "$INSTDIR"
  FileOpen $0 "$INSTDIR\dzbench.exe" w
  FileWrite $0 "old"
  FileClose $0
  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\电赛工作台" "DisplayName" "电赛工作台"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\电赛工作台" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\电赛工作台" "InstallLocation" "$INSTDIR"
  CreateShortCut "$SMPROGRAMS\电赛工作台.lnk" "$INSTDIR\dzbench.exe"
SectionEnd
Section "Uninstall"
  Delete "$INSTDIR\dzbench.exe"
  Delete "$SMPROGRAMS\电赛工作台.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\电赛工作台"
SectionEnd
