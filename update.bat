@echo off
rem Update to the latest version from GitHub. Your downloads and transcripts are kept.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
if errorlevel 1 echo Update failed. See the message above.
pause
