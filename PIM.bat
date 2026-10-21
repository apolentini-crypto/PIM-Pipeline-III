@echo off
rem Double-click to open the PIM window. Close this console to stop it.
cd /d "%~dp0"
rem Stop any PIM already listening on port 8766 (an old one would block the new one).
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8766" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
echo Starting the PIM window...
python -m pim.cli.main ui
echo.
echo The PIM window has stopped (see any error above). Press any key to close.
pause >nul
