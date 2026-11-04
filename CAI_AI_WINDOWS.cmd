@echo off
setlocal
cd /d "%~dp0"
set "ATC_OLLAMA_EXE=ollama"
where ollama >nul 2>nul
if not errorlevel 1 goto install_model
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
  set "ATC_OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
  goto install_model
)
echo Chua tim thay Ollama tren may.
echo Trinh duyet se mo trang tai Ollama chinh thuc.
echo Cai Ollama, mo Ollama tu Start Menu, roi chay lai file nay.
start "" "https://ollama.com/download/windows"
pause
exit /b 1
:install_model
echo Se tai model qwen2.5:3b de suy luan AI tren may, khong can API tra phi.
echo Can Internet, vai GB dia trong va du RAM; toc do tuy may.
echo Hay dam bao Ollama dang chay trong Start Menu / khay he thong.
"%ATC_OLLAMA_EXE%" pull qwen2.5:3b
if errorlevel 1 goto failed
echo.
echo Da co model. Mo website, bam KET NOI AI, giu ten qwen2.5:3b va bam KIEM TRA VA BAT AI.
echo Neu chua mo website, chay MO_WEBSITE.cmd.
pause
exit /b 0
:failed
echo Khong tai duoc model. Kiem tra Ollama dang chay, Internet va dung luong o dia.
echo Website van co the theo doi / backtest bang cong cu Python.
pause
exit /b 1
