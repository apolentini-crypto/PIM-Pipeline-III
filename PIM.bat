@echo off
rem Double-click to open the PIM window. Close this console to stop it.
cd /d "%~dp0"
rem Stop any PIM already listening on port 8766 (an old one would block the new one).
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8766" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
echo Starting the PIM window...
set PIM_UI_ARGS=
:run
python -m pim.cli.main ui %PIM_UI_ARGS%
rem Exit code 75 = the window's code changed and the page asked for a restart; start again without a new browser tab.
if errorlevel 75 if not errorlevel 76 (
  echo Window updated - restarting...
  set PIM_UI_ARGS=--no-browser
  goto run
)
echo.
echo The PIM window has stopped (see any error above). Press any key to close.
pause >nul
