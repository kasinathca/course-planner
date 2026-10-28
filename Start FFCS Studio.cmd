@echo off
setlocal
set "FFCS_ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%FFCS_ROOT%scripts\start.ps1" %*
set "FFCS_EXIT=%ERRORLEVEL%"
if not "%FFCS_EXIT%"=="0" (
  echo.
  echo FFCS Studio did not start. Review the message above.
  pause
)
exit /b %FFCS_EXIT%
