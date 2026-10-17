#!/usr/bin/env bash
# Update this folder to the latest version from GitHub (macOS / Linux).
# Keeps your downloads, transcripts and settings; only the program files change.
set -euo pipefail
cd "$(dirname "$0")"
dest="$PWD"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading the latest version…"
curl -fsSL "https://github.com/andongw-gh/Youtube-Transcriber/archive/HEAD.zip" -o "$tmp/src.zip"
unzip -q "$tmp/src.zip" -d "$tmp/x"
src="$(find "$tmp/x" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

echo "Copying files into $dest"
# update.sh itself is skipped: bash reads this file while it runs.
tar -C "$src" --exclude=./update.sh -cf - . | tar -C "$dest" -xf -

if [ -x .venv/bin/python ]; then
  echo "Updating dependencies…"
  .venv/bin/python -m pip install -q -e .
else
  echo "No Python environment yet; run.sh will create it on first start."
fi
echo
echo "Update complete. Start the app with ./run.sh"
