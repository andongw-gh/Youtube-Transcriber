#!/usr/bin/env bash
# Start the YouTube Transcriber web app. Creates a virtualenv and installs
# dependencies the first time; after that it just launches.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

if ! python -c "import yt_transcriber, faster_whisper, yt_dlp, fastapi" 2>/dev/null; then
  echo "Installing dependencies (one-time, a few minutes)…"
  python -m pip install --upgrade pip >/dev/null
  python -m pip install -e .
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Note: ffmpeg was not found. Install it for best results:"
  echo "  macOS:  brew install ffmpeg      Debian/Ubuntu:  sudo apt install ffmpeg"
fi

exec yt-transcriber serve "$@"
