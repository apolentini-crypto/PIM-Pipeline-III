@echo off
title PIM
rem Double-click to open the PIM window. Close this console to stop it.                              
rem One window only (2026-11-18): if PIM is already running, this does NOT start a second one -
rem it opens your browser to the running window and closes itself.
cd /d "%~dp0"
echo Starting the PIM window...
set PIM_UI_ARGS=
:run
python -m pim.cli.main ui %PIM_UI_ARGS%
set PIM_EXIT=%errorlevel%
rem 75 = the window's code changed and the page asked for a restart; start again without a new browser tab.
if "%PIM_EXIT%"=="75" (
  echo Window updated - restarting...
  set PIM_UI_ARGS=--no-browser
  goto run
)
rem 3 = PIM is already running; the browser was opened to it. Nothing was started.
if "%PIM_EXIT%"=="3" (
  echo.
  echo PIM is already running - your browser was opened to it. This extra console closes in 5 seconds.
  timeout /t 5 >nul
  exit /b 0
)
rem 4 = port 8766 is taken by something that is not a PIM window.
echo.
echo The PIM window has stopped (see any message above). Press any key to close.
pause >nul
