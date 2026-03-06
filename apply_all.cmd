@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_apply_context_safe.ps1"
if errorlevel 1 exit /b %errorlevel%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_apply_ntp_link_only.ps1"
if errorlevel 1 exit /b %errorlevel%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_disable_ntp_banner.ps1"
exit /b %errorlevel%
