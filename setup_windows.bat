@echo off
setlocal
chcp 65001 >nul
echo [INFO] setup_windows.bat is now a compatibility wrapper.
call "%~dp0bootstrap_windows.bat"
