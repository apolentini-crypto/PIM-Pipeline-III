@echo off
rem Double-click to open the PIM window. Closes when you close this console.
cd /d "%~dp0"
python -m pim.cli.main ui
pause
