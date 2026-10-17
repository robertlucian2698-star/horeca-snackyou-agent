@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo Extrage intreaga arhiva ZIP inainte de pornire.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" -B "%~dp0install_diagnostic.py"
pause
