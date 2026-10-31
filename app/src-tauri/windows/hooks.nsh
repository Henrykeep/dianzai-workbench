; 文件名 / 安装目录用 ASCII 的 productName（XinTai）；开始菜单显示中文名 芯台（Tauri 在 POSTINSTALL 之前建好 ${PRODUCTNAME}.lnk）
!macro NSIS_HOOK_POSTINSTALL
  ${If} ${FileExists} "$SMPROGRAMS\${PRODUCTNAME}.lnk"
    Delete "$SMPROGRAMS\芯台.lnk"
    Rename "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$SMPROGRAMS\芯台.lnk"
  ${EndIf}
!macroend
!macro NSIS_HOOK_PREUNINSTALL
  Delete "$SMPROGRAMS\芯台.lnk"
!macroend
