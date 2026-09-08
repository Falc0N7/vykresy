@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

REM --- Read version from VERSION file ---
set APP_VERSION=unknown
if exist "%~dp0VERSION" (
    set /p APP_VERSION=<"%~dp0VERSION"
)

echo ==================================================
echo   PREJMENOVANI VYKRESU - PRODUCTION v%APP_VERSION%
echo   Automaticka adaptace HW + auto-instalace zavislosti
echo ==================================================
echo.
echo Adresar aplikace: %~dp0
echo.

REM --- Kontrola Pythonu (python / py launcher) ---
set PYTHON_CMD=
where python >nul 2>nul
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=py"
    )
)

if not defined PYTHON_CMD (
    echo [CHYBA] Python nebyl nalezen v PATH.
    echo.
    echo Reseni:
    echo   1. Nainstalujte Python 3.10+ z https://www.python.org/downloads/
    echo   2. Pri instalaci ZASKRTNETE "Add Python to PATH" a "pip"
    echo   3. Restartujte PC a spustte znovu run.bat
    echo.
    echo Offline alternativa: zkopirujte portable Python do PATH.
    echo.
    pause
    exit /b 1
)

echo [INFO] Pouzivam: %PYTHON_CMD%
%PYTHON_CMD% --version 2>&1
if %errorlevel% neq 0 (
    echo [CHYBA] Nepodarilo se zjistit verzi Pythonu.
    pause
    exit /b 1
)

REM Volitelna kontrola verze Python >=3.10 (fail-fast, ale main.py to take zkontroluje s GUI)
%PYTHON_CMD% -c "import sys; exit(0 if sys.version_info>=(3,10) else 1)" 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [CHYBA] Je vyzadovan Python 3.10 nebo novější.
    %PYTHON_CMD% --version
    echo Nainstalujte aktualni Python z https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo [INFO] Spoustim aplikaci (prvni spusteni muze stahovat zavislosti ~3 GB a model ~7 GB, celkem ~10 GB)...
echo        Nevypinejte PC, sledujte prubeh v okne aplikace.
echo.

REM --- Spusteni aplikace (main.py si sam nainstaluje chybejici zavislosti/model) ---
%PYTHON_CMD% "%~dp0main.py"
set EXIT_CODE=%errorlevel%

if %EXIT_CODE% neq 0 (
    echo.
    echo ==================================================
    echo [UPOZORNENI] Program skoncil s chybou (kod: %EXIT_CODE%).
    echo ==================================================
    echo Zkontrolujte:
    echo   - Log soubor: %~dp0rename_drawings.log
    echo   - Pripojeni k internetu (prvni spusteni vyzaduje internet)
    echo   - Dostatek mista na disku (alespon 10 GB volno)
    echo   - Prava k zapisu do adresare aplikace
    echo.
    echo Tip: spustte rucne pro detail:
    echo   %PYTHON_CMD% "%~dp0main.py"
    echo   pip install -r "%~dp0requirements.txt"
    echo.
    pause
    exit /b %EXIT_CODE%
)

endlocal
