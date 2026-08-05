@echo off
REM ============================================================
REM   Construiește horeca-snackyou.exe (rulează pe Windows)
REM   Necesită Python 3.10+ instalat (cu "Add to PATH" bifat).
REM   Dublu-click pe acest fisier SAU ruleaza-l din CMD.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/4] Verific Python...
where python >nul 2>nul
if errorlevel 1 (
  echo    EROARE: Python nu e instalat sau nu e in PATH.
  echo    Descarca de la https://www.python.org/downloads/ si bifeaza
  echo    "Add python.exe to PATH" la instalare. Apoi ruleaza din nou.
  pause
  exit /b 1
)
python --version

echo.
echo [2/4] Instalez dependintele...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 ( echo    EROARE la pip install. & pause & exit /b 1 )

echo.
echo [3/4] Construiesc horeca-snackyou.exe...
pyinstaller --onefile --console --name horeca-snackyou ^
  --collect-all httpx --collect-all httpcore --collect-all certifi ^
  --hidden-import pymysql --hidden-import pymysql.cursors ^
  horeca_snackyou.py
if errorlevel 1 ( echo    EROARE la build. & pause & exit /b 1 )

echo.
echo [4/4] GATA.
echo    Executabilul e in folderul:  dist\horeca-snackyou.exe
echo    Copiaza-l unde vrei si dublu-click pe el ca sa pornesti configurarea.
echo.
pause
endlocal
