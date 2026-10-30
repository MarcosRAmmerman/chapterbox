
    
  
@echo off
setlocal EnableExtensions

rem ============================================================
rem ChapterBox: start local Chatterbox TTS if needed, then launch
rem the existing ChapterBox menu. Save next to Run ChapterBox.bat.
rem ============================================================

set "CHAPTERBOX_DIR=%~dp0"
set "CHAPTERBOX_LAUNCHER=%CHAPTERBOX_DIR%Run ChapterBox.bat"
set "API_DIR=%USERPROFILE%\chatterbox-local\chatterbox-tts-api"
set "API_PYTHON=%API_DIR%\.venv\Scripts\python.exe"
set "HEALTH_URL=http://127.0.0.1:4123/health"

cd /d "%CHAPTERBOX_DIR%"
echo ========================================
echo           CHAPTERBOX LAUNCHER
echo ========================================
echo.

if not exist "%CHAPTERBOX_LAUNCHER%" (
    echo ERROR: Cannot find "Run ChapterBox.bat".
    echo Place this file in the ChapterBox project folder.
    goto :error
)

call :check_health
if not errorlevel 1 (
    echo Chatterbox server is already running.
    goto :launch_chapterbox
)

echo Chatterbox API is offline. Starting the local server...
if not exist "%API_PYTHON%" (
    echo ERROR: Chatterbox Python not found:
    echo   %API_PYTHON%
    goto :error
)
if not exist "%API_DIR%\main.py" (
    echo ERROR: Chatterbox server main.py not found:
    echo   %API_DIR%\main.py
    goto :error
)

rem Launch in a second console. Do not use ERRORLEVEL from START:
rem we determine success only by checking the actual /health API.
start "Chatterbox TTS Server" /D "%API_DIR%" cmd.exe /k ""%API_PYTHON%" main.py"

echo Waiting for Chatterbox to finish loading the model...
echo The server may need a few minutes on CPU.
set /a ATTEMPTS=0
:wait_server
call :check_health
if not errorlevel 1 goto :server_ready
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ 120 (
    echo.
    echo ERROR: Chatterbox did not become available at:
    echo   %HEALTH_URL%
    echo Check the Chatterbox TTS Server window for errors.
    goto :error
)
timeout /t 3 /nobreak >nul
goto :wait_server

:server_ready
echo Chatterbox API is ready.

:launch_chapterbox
echo.
echo Starting ChapterBox...
call "%CHAPTERBOX_LAUNCHER%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo ChapterBox exited with code %RESULT%.
    pause
)
exit /b %RESULT%

:check_health
rem The check returns zero only for an HTTP 200 response.
powershell.exe -NoProfile -NonInteractive -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%HEALTH_URL%' -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
exit /b %ERRORLEVEL%

:error
echo.
pause
exit /b 1

