; MotionSilo Windows installer
; Build with:
; makensis /DPRODUCT_VERSION=0.1.0 /DSOURCE_EXE="...\MotionSilo-0.1.0.exe" MotionSilo.nsi

!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "0.1.0"
!endif
!ifndef SOURCE_EXE
  !error "SOURCE_EXE must point to the packaged MotionSilo executable"
!endif

Unicode true
Name "MotionSilo"
Caption "MotionSilo ${PRODUCT_VERSION} Setup"
OutFile "MotionSilo-${PRODUCT_VERSION}-Setup.exe"
InstallDir "$PROGRAMFILES64\MotionSilo"
InstallDirRegKey HKLM "Software\MotionSilo" "InstallDir"
RequestExecutionLevel admin
ManifestSupportedOS win10
VIProductVersion "${PRODUCT_VERSION}.0"
VIAddVersionKey ProductName "MotionSilo"
VIAddVersionKey CompanyName "J. E. Lollis"
VIAddVersionKey FileDescription "Motion-triggered camera recorder"
VIAddVersionKey FileVersion "${PRODUCT_VERSION}"
VIAddVersionKey LegalCopyright "Copyright (c) 2026 J. E. Lollis"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "MotionSilo" SecMain
  SetOutPath "$INSTDIR"
  File /oname=MotionSilo-${PRODUCT_VERSION}.exe "${SOURCE_EXE}"
  WriteRegStr HKLM "Software\MotionSilo" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\MotionSilo"
  CreateShortCut "$SMPROGRAMS\MotionSilo\MotionSilo.lnk" "$INSTDIR\MotionSilo-${PRODUCT_VERSION}.exe"
  CreateShortCut "$SMPROGRAMS\MotionSilo\Uninstall MotionSilo.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\MotionSilo.lnk" "$INSTDIR\MotionSilo-${PRODUCT_VERSION}.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\MotionSilo.lnk"
  Delete "$SMPROGRAMS\MotionSilo\MotionSilo.lnk"
  Delete "$SMPROGRAMS\MotionSilo\Uninstall MotionSilo.lnk"
  RMDir "$SMPROGRAMS\MotionSilo"
  Delete "$INSTDIR\MotionSilo-${PRODUCT_VERSION}.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\MotionSilo"
SectionEnd
