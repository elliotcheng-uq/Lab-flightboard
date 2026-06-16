@echo off
REM ---------------------------------------------------------------------------
REM Lab Flightboard launcher (Windows)
REM Starts the billboard server, then opens it full-screen in Edge kiosk mode.
REM Edit billboard_config.json (copy from examples/billboard_config.example.json)
REM to add your own instruments. With no config it shows the placeholder demo.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set PY="%USERPROFILE%\AppData\Local\anaconda3\envs\gdsenv\python.exe"
if not exist %PY% set PY=python

start "Lab Flightboard Server" %PY% examples\billboard_app.py

REM give the server a moment to come up, then open the kiosk display
timeout /t 3 /nobreak >nul
start msedge --kiosk "http://localhost:5200" --edge-kiosk-type=fullscreen --no-first-run

echo.
echo Lab Flightboard is starting.
echo   - Display:  http://localhost:5200
echo   - To stop:  close the "Lab Flightboard Server" window
echo   - Kiosk exit: Alt+F4
echo.
endlocal
