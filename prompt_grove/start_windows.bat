@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Dependency install failed. Check Python and your internet connection, then retry.
  pause
  exit /b 1
)
python app.py
pause
