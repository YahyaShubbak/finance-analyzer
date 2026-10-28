@echo off
rem Starts the Local Finance Analyzer. The backend serves the web interface
rem itself - one command, one local server. Close this window (or press
rem Ctrl+C) to stop the app.
rem
rem   run.bat               start with the settings chosen during installation
rem   run.bat --port 8421   use another port this time
rem   run.bat --open        also open the browser
rem
rem No parenthesized blocks on purpose: a ")" in the folder path (e.g.
rem "C:\Users\Max (Privat)") would end such a block early.
setlocal
set "APP_PYTHON=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" goto not_installed
if not exist "%~dp0frontend\dist\index.html" echo WARNING: the web interface has not been built yet - run install.bat.
cd /d "%~dp0backend"
"%APP_PYTHON%" -m app %*
set "APP_EXIT=%ERRORLEVEL%"
rem Keep the window open on errors so the message can be read.
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%

:not_installed
echo The app is not installed yet (backend\.venv is missing).
echo Run install.bat first.
pause
exit /b 1
