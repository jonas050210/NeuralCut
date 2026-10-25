; NeuralCut NSIS hooks: Desktop shortcut (Start Menu entry is created by
; the Tauri NSIS template itself). User projects/app data live outside
; $INSTDIR and are never touched by install/uninstall.
!macro NSIS_HOOK_POSTINSTALL
  CreateShortcut "$DESKTOP\NeuralCut.lnk" "$INSTDIR\neuralcut.exe"
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$DESKTOP\NeuralCut.lnk"
!macroend
