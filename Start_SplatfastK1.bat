@echo off
REM ============================================================
REM  SplatfastK1 launcher — double-click this file to start.
REM
REM  First time you run it:
REM    1. Verifies Python 3.10+ is installed (opens download page if not).
REM    2. Installs the app's Python dependencies (PyQt6, keyring, etc.).
REM    3. Creates Start Menu + Desktop shortcuts so you can find the app
REM       via Windows search from now on.
REM    4. Launches the app. On first launch the app shows a Setup screen
REM       that downloads Brush, BlendSplat, COLMAP for you.
REM
REM  Subsequent runs: just launches the app instantly.
REM ============================================================

setlocal
cd /d "%~dp0"

REM --- Check Python ---
where /q pythonw.exe
if errorlevel 1 (
    where /q python.exe
    if errorlevel 1 (
        echo.
        echo SplatfastK1 needs Python 3.10 or newer.
        echo Opening the download page in your browser...
        echo.
        echo IMPORTANT: When installing Python, check the
        echo            "Add Python to PATH" checkbox at the bottom.
        echo.
        start https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

REM --- Verify Python version (>= 3.10, matching pyproject.toml requires-python) ---
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo.
    echo Your Python is too old. SplatfastK1 needs Python 3.10 or newer.
    echo Opening the download page...
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

REM --- Detect Microsoft Store Python and warn ---
REM Store Python runs in a sandbox that breaks desktop-app features:
REM   - Taskbar shows the Python icon instead of ours (AppUserModelID
REM     ignored)
REM   - %APPDATA% is sometimes redirected to a per-app sandbox
REM   - pip can have subtle path resolution issues
REM The fix is to install from python.org instead.
python -c "import sys; sys.exit(1 if 'WindowsApps' in sys.executable else 0)"
if errorlevel 1 (
    echo.
    echo ============================================================
    echo   NOTICE: Microsoft Store Python detected
    echo ============================================================
    echo.
    echo The Python you have installed is from the Microsoft Store.
    echo Store Python runs in a sandbox that causes some annoyances:
    echo   - Taskbar shows the Python icon instead of SplatfastK1's
    echo   - Some advanced features may not work correctly
    echo.
    echo For best results, install Python from python.org instead:
    echo   https://www.python.org/downloads/
    echo.
    echo The app WILL still run on Store Python, just with these quirks.
    echo.
    pause
)

REM --- Install Python dependencies if needed ---
REM We check for a sentinel file so this only runs once on first launch
REM (or whenever pyproject.toml is newer than the sentinel).
set "SENTINEL=%LOCALAPPDATA%\SplatfastK1\.deps_installed"
if not exist "%SENTINEL%" goto :install_deps
for %%F in (pyproject.toml) do set "PYPROJECT_TIME=%%~tF"
for %%F in ("%SENTINEL%") do set "SENTINEL_TIME=%%~tF"
if "%PYPROJECT_TIME%" GTR "%SENTINEL_TIME%" goto :install_deps
goto :create_shortcuts

:install_deps
echo.
echo Installing SplatfastK1 dependencies (one-time setup, ~30 sec)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e .
if errorlevel 1 (
    echo.
    echo Dependency install failed. Try running this from a fresh terminal:
    echo     python -m pip install -e .
    pause
    exit /b 1
)
if not exist "%LOCALAPPDATA%\SplatfastK1" mkdir "%LOCALAPPDATA%\SplatfastK1"
echo done > "%SENTINEL%"
echo Dependencies installed.

:create_shortcuts
REM --- Create Start Menu + Desktop shortcuts so the app is findable ---
REM
REM Critical detail: on Windows 10/11 with OneDrive sign-in (the default for
REM most users), the Desktop folder is REDIRECTED to %USERPROFILE%\OneDrive\
REM Desktop, NOT %USERPROFILE%\Desktop. Same can apply to Start Menu in
REM enterprise / roaming-profile setups.
REM
REM Trying to write the shortcut to the wrong path silently fails with a
REM DirectoryNotFoundException — meaning the user clones the repo, runs the
REM launcher, and gets NO Windows-search entry, no Desktop icon, looks broken.
REM
REM Fix: do the whole thing in PowerShell where we have access to
REM [Environment]::GetFolderPath() which returns the real OS path for these
REM special folders, OneDrive-redirected or not.
set "ICON_FILE=%~dp0desktop\icons\splatforge.ico"
set "TARGET=%~dp0Start_SplatfastK1.bat"
set "WORKDIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$smDir = [Environment]::GetFolderPath('Programs');" ^
  "$desktopDir = [Environment]::GetFolderPath('Desktop');" ^
  "$smLnk = Join-Path $smDir 'SplatfastK1.lnk';" ^
  "$dLnk = Join-Path $desktopDir 'SplatfastK1.lnk';" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "function Make($path) {" ^
  "  if (Test-Path $path) { return };" ^
  "  $s = $ws.CreateShortcut($path);" ^
  "  $s.TargetPath = '%TARGET%';" ^
  "  $s.WorkingDirectory = '%WORKDIR%';" ^
  "  $s.IconLocation = '%ICON_FILE%';" ^
  "  $s.Description = 'SplatfastK1 - turn video into 3D Gaussian splat';" ^
  "  $s.WindowStyle = 7;" ^
  "  $s.Save();" ^
  "}" ^
  "Make $smLnk;" ^
  "Make $dLnk" 2>nul

:launch
REM --- Launch the app ---
REM pythonw.exe runs without showing a console window (matches the
REM polished-app UX). The window will appear in 2-3 seconds.
where /q pythonw.exe
if errorlevel 1 (
    REM No pythonw — fall back to python.exe (will show a console too)
    start "" python -m desktop.main
) else (
    start "" pythonw -m desktop.main
)
endlocal
