@echo off
setlocal enabledelayedexpansion
title StoMount Installer
echo ========================================================
echo                 StoMount Installer
echo        Android Adopted Storage Manager for Windows
echo ========================================================
echo.

set "INSTALL_DIR=%LOCALAPPDATA%\Programs\StoMount"
set "EXE_SRC=%~dp0dist\StoMount.exe"

if not exist "!EXE_SRC!" (
    set "EXE_SRC=%~dp0StoMount.exe"
)

if not exist "!EXE_SRC!" (
    echo [ERROR] StoMount.exe was not found in this folder or dist\ folder!
    echo Please make sure StoMount.exe is located alongside this installer.
    echo.
    pause
    exit /b 1
)

echo [*] Installing StoMount to: !INSTALL_DIR!...
if not exist "!INSTALL_DIR!" mkdir "!INSTALL_DIR!"

copy /y "!EXE_SRC!" "!INSTALL_DIR!\StoMount.exe" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy files to !INSTALL_DIR!.
    pause
    exit /b 1
)

echo [*] Creating Start Menu and Desktop shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
  "$startMenu = [Environment]::GetFolderPath('Programs'); " ^
  "$target = '%INSTALL_DIR%\StoMount.exe'; " ^
  "$scDesk = $ws.CreateShortcut(\"$desktop\StoMount.lnk\"); " ^
  "$scDesk.TargetPath = $target; " ^
  "$scDesk.WorkingDirectory = '%INSTALL_DIR%'; " ^
  "$scDesk.Description = 'StoMount - Android Adopted Storage Manager'; " ^
  "$scDesk.Save(); " ^
  "$scStart = $ws.CreateShortcut(\"$startMenu\StoMount.lnk\"); " ^
  "$scStart.TargetPath = $target; " ^
  "$scStart.WorkingDirectory = '%INSTALL_DIR%'; " ^
  "$scStart.Description = 'StoMount - Android Adopted Storage Manager'; " ^
  "$scStart.Save(); "

echo [*] Registering in Windows Add/Remove Programs...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\StoMount" /v "DisplayName" /t REG_SZ /d "StoMount" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\StoMount" /v "DisplayVersion" /t REG_SZ /d "1.1.0" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\StoMount" /v "Publisher" /t REG_SZ /d "StoMount" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\StoMount" /v "InstallLocation" /t REG_SZ /d "!INSTALL_DIR!" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\StoMount" /v "DisplayIcon" /t REG_SZ /d "!INSTALL_DIR!\StoMount.exe,0" /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\StoMount" /v "UninstallString" /t REG_SZ /d "!INSTALL_DIR!\Uninstall-StoMount.bat" /f >nul 2>&1

:: Create Uninstaller
(
echo @echo off
echo echo Uninstalling StoMount...
echo taskkill /f /im StoMount.exe ^>nul 2^>^&1
echo del /q "%%USERPROFILE%%\Desktop\StoMount.lnk" ^>nul 2^>^&1
echo del /q "%%APPDATA%%\Microsoft\Windows\Start Menu\Programs\StoMount.lnk" ^>nul 2^>^&1
echo reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\StoMount" /f ^>nul 2^>^&1
echo echo StoMount has been uninstalled. You can now delete the folder "!INSTALL_DIR!".
echo pause
) > "!INSTALL_DIR!\Uninstall-StoMount.bat"

echo.
echo ========================================================
echo       [SUCCESS] StoMount Installed Successfully!
echo ========================================================
echo.
echo - A shortcut has been placed on your Desktop.
echo - StoMount is now available in your Start Menu.
echo.
set /p LAUNCH="Would you like to launch StoMount now? (Y/N): "
if /i "!LAUNCH!"=="Y" (
    start "" "!INSTALL_DIR!\StoMount.exe"
)
exit /b 0
