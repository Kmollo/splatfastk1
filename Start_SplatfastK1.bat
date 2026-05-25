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
REM This runs every launch but is a no-op if the shortcut already exists.
REM Without this, users who clone the repo can only launch the app by
REM navigating to the folder and double-clicking the .bat. Adding a Start
REM Menu entry means typing "splat" in Windows search finds it.
set "SHORTCUT_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
set "SHORTCUT_FILE=%SHORTCUT_DIR%\SplatfastK1.lnk"
set "DESKTOP_SHORTCUT=%USERPROFILE%\Desktop\SplatfastK1.lnk"
set "ICON_FILE=%~dp0desktop\icons\splatforge.ico"
set "TARGET=%~dp0Start_SplatfastK1.bat"

if not exist "%SHORTCUT_FILE%" (
    echo Adding SplatfastK1 to Start Menu...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$w = New-Object -ComObject WScript.Shell;" ^
        "$s = $w.CreateShortcut('%SHORTCUT_FILE%');" ^
        "$s.TargetPath = '%TARGET%';" ^
        "$s.WorkingDirectory = '%~dp0';" ^
        "$s.IconLocation = '%ICON_FILE%';" ^
        "$s.Description = 'SplatfastK1 - turn video into 3D Gaussian splat';" ^
        "$s.WindowStyle = 7;" ^
        "$s.Save()" 2>nul
)

if not exist "%DESKTOP_SHORTCUT%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$w = New-Object -ComObject WScript.Shell;" ^
        "$s = $w.CreateShortcut('%DESKTOP_SHORTCUT%');" ^
        "$s.TargetPath = '%TARGET%';" ^
        "$s.WorkingDirectory = '%~dp0';" ^
        "$s.IconLocation = '%ICON_FILE%';" ^
        "$s.Description = 'SplatfastK1 - turn video into 3D Gaussian splat';" ^
        "$s.WindowStyle = 7;" ^
        "$s.Save()" 2>nul
)

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
