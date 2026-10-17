# Update this folder to the latest version from GitHub.
# Keeps your downloads, transcripts and settings; only the program files change.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

$dest = Split-Path -Parent $MyInvocation.MyCommand.Path
$zip = Join-Path $env:TEMP "yt-transcriber-update.zip"
$tmp = Join-Path $env:TEMP "yt-transcriber-update"

Write-Host "Downloading the latest version..."
Invoke-WebRequest -Uri "https://github.com/andongw-gh/Youtube-Transcriber/archive/HEAD.zip" -OutFile $zip
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$src = (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName

Write-Host "Copying files into $dest"
Get-ChildItem -Path $src -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($src.Length).TrimStart('\')
    if ($rel -ieq 'update.bat') { return }   # never overwrite the launcher that is running us
    $target = Join-Path $dest $rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $target -Force
}
Remove-Item $zip -Force
Remove-Item $tmp -Recurse -Force

# Reinstall into the existing environment so new dependencies are picked up.
$venv = Join-Path $dest ".venv"
if ($dest -match "\\OneDrive\\") { $venv = Join-Path $env:LOCALAPPDATA "yt-transcriber\venv" }
$python = Join-Path $venv "Scripts\python.exe"
if (Test-Path $python) {
    Write-Host "Updating dependencies..."
    & $python -m pip install -q -e $dest
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
} else {
    Write-Host "No Python environment yet; run.bat will create it on first start."
}
Write-Host ""
Write-Host "Update complete. Start the app with run.bat."
