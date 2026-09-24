@echo off
setlocal
cd /d "%~dp0"

if not defined BRANDVEILIGHEID_DATA_DIR set "BRANDVEILIGHEID_DATA_DIR=%LOCALAPPDATA%\Triacon\Brandveiligheidsinspectie"

if exist ".venv\Scripts\python.exe" goto checkdeps

echo Eerste installatie van de Brandveiligheidsinspectie-app...
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv .venv
    goto install
)

where python >nul 2>nul
if %errorlevel%==0 (
    python -m venv .venv
    goto install
)

echo.
echo Python 3 is niet gevonden.
echo Installeer Python 3.11 of nieuwer via https://www.python.org/downloads/windows/
echo Kies tijdens de installatie ook "Add Python to PATH".
pause
exit /b 1

:install
if not exist ".venv\Scripts\python.exe" (
    echo Het aanmaken van de Python-omgeving is mislukt.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installatie van de app-onderdelen is mislukt.
    pause
    exit /b 1
)

:checkdeps
".venv\Scripts\python.exe" -c "import pypdfium2,streamlit; from importlib.metadata import version; assert tuple(map(int,version('streamlit').split('.')[:2])) >= (1,61)" >nul 2>nul
if errorlevel 1 goto install

:run
echo.
echo Brandveiligheidsinspectie wordt gestart op poort 8502.
echo Projecten, rapporten en foto's worden blijvend opgeslagen in:
echo %BRANDVEILIGHEID_DATA_DIR%
echo Sluit dit venster niet zolang de app beschikbaar moet blijven.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8502
pause
