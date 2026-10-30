@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\bootstrap.ps1"
if errorlevel 1 (
  echo.
  echo ChapterBox could not start. Read the error above.
  pause
)
endlocal
