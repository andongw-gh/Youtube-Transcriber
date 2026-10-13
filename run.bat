@echo off
rem Start the YouTube Transcriber web app on Windows. Creates a virtual environment and
rem installs dependencies the first time; after that it just launches.
setlocal
cd /d "%~dp0"

rem Keep the virtual environment out of OneDrive-synced folders: syncing thousands of
rem library files is slow and can break installs. Everything else stays in this folder.
set "VENV=%CD%\.venv"
echo %CD% | find /i "\OneDrive\" >nul && set "VENV=%LOCALAPPDATA%\yt-transcriber\venv"

if not exist "%VENV%\Scripts\python.exe" (
  echo Creating virtual environment in "%VENV%"...
  py -3 -m venv "%VENV%" 2>nul || python -m venv "%VENV%"
  if not exist "%VENV%\Scripts\python.exe" (
    echo.
    echo Python 3.10 or newer was not found.
    echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH"
    echo in the installer, then run this file again.
    echo.
    pause
    exit /b 1
  )
)
call "%VENV%\Scripts\activate.bat"

python -c "import yt_transcriber, faster_whisper, yt_dlp, fastapi" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies (one-time, a few minutes^)...
  python -m pip install --upgrade pip >nul
  python -m pip install -e .
  if errorlevel 1 (
    echo.
    echo Installing dependencies failed. Check your internet connection and run this file again.
    echo.
    pause
    exit /b 1
  )
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo Note: ffmpeg was not found. Install it for best results, then restart this app:
  echo     winget install Gyan.FFmpeg
)

yt-transcriber serve %*
if errorlevel 1 pause
endlocal
