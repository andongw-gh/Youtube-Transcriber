@echo off
rem Start the YouTube Transcriber web app on Windows. Creates a virtualenv and
rem installs dependencies the first time; after that it just launches.
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat

python -c "import yt_transcriber, faster_whisper, yt_dlp, fastapi" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies (one-time, a few minutes)...
  python -m pip install --upgrade pip >nul
  python -m pip install -e .
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo Note: ffmpeg was not found. Install it for best results:  winget install Gyan.FFmpeg
)

yt-transcriber serve %*
endlocal
