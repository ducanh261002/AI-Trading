@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 "%~dp0scripts\windows.py" setup
goto finished
:use_python
where python >nul 2>&1
if errorlevel 1 goto missing_python
python "%~dp0scripts\windows.py" setup
:finished
set "ATC_RESULT=%ERRORLEVEL%"
echo.
if not "%ATC_RESULT%"=="0" echo Cai dat chua thanh cong. Hay chup loi tren cua so nay.
pause
exit /b %ATC_RESULT%
:missing_python
echo Chua tim thay Python. Xem docs\WINDOWS_LOCAL.md de cai Python truoc.
pause
exit /b 1
