@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv-windows\Scripts\python.exe" goto missing_setup
"%~dp0.venv-windows\Scripts\python.exe" "%~dp0scripts\windows.py" start
set "ATC_RESULT=%ERRORLEVEL%"
echo.
echo Website da dung. Ban co the dong cua so nay.
pause
exit /b %ATC_RESULT%
:missing_setup
echo Hay chay CAI_DAT_WINDOWS.cmd truoc. Website chua duoc khoi dong.
pause
exit /b 1
