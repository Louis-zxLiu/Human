@echo off
setlocal
chcp 65001 >nul

echo [INFO] setup_windows.bat has been downgraded.
echo [INFO] Collaborators should use bootstrap_windows.bat as the first entrypoint.
call "%~dp0bootstrap_windows.bat"
