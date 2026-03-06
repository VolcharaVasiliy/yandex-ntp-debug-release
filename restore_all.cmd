@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_restore_newtab_backup.ps1"
if errorlevel 1 exit /b %errorlevel%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_restore_ntp_banner.ps1"
exit /b %errorlevel%
