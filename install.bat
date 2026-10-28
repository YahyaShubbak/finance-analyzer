@echo off
rem Installs (or updates) the Local Finance Analyzer on Windows.
rem
rem   install.bat          interactive: explains each step and asks before changing anything
rem   install.bat -Yes     non-interactive: use defaults / previous choices
rem   install.bat -Help    all options
rem
rem The installer itself is install.ps1: PowerShell handles paths with spaces,
rem parentheses or umlauts and version checks far more reliably than batch.
rem -ExecutionPolicy Bypass applies to this one script only and changes no
rem system setting.
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %ERRORLEVEL%
