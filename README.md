# YouTube Download & Transcribe

Paste a YouTube link. **Download** the video (MP4) or just its audio (MP3 / M4A), one
video or a whole playlist, or **transcribe** it in **Chinese (中文)** or **English** with
automatic language detection. Everything runs on your own computer: media is fetched
with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and speech is transcribed with
[Whisper](https://github.com/openai/whisper) via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper). No API key, no cost per video.

Features

- One local web app with two tabs: **Transcribe** and **Download**.
- Transcripts as plain text, SRT or WebVTT subtitles, or JSON with timestamps.
- Chinese output can be forced to Simplified (简体) or Traditional (繁體).
- Downloads as MP4 up to a chosen resolution (default 1080p) or as MP3 / M4A audio.
- Whole playlists in one go, numbered, into a folder named after the playlist.
  A broken video does not stop the rest; failures are listed at the end.
- Queue several jobs; downloads and transcriptions run on separate workers.
- Command line mode for scripting and batch jobs.
- Files land in `downloads` and `transcripts` next to the app. `update.bat` /
  `update.sh` pulls the latest version without touching them.

## Requirements

- Python 3.10 or newer.
- [ffmpeg](https://ffmpeg.org/) (strongly recommended; used to decode the audio).
  - macOS: `brew install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
  - Debian/Ubuntu: `sudo apt install ffmpeg`
- Optional: an NVIDIA GPU makes the larger Whisper models usable (see [GPU](#gpu)).

## Quick start

```bash
git clone <this repository>
cd Youtube-Transcriber
./run.sh          # macOS / Linux
run.bat           # Windows (double-click works too)
```

The first run creates a virtual environment and installs the dependencies, then opens
<http://127.0.0.1:8000> in your browser. Paste a link and press **Transcribe**.

No git? Use the green **Code → Download ZIP** button on GitHub and extract the folder
instead of cloning.

On Windows, if the folder lives inside OneDrive, the Python environment is created in
`%LOCALAPPDATA%\yt-transcriber\venv` rather than next to the code, so OneDrive does not
try to sync thousands of library files. Transcripts still land in the app folder.

The first transcription with a given model downloads that model (about 500 MB for
`small`, 1.5 GB for `medium`, 3 GB for `large-v3`). Later runs reuse the cached copy.

Manual install, if you prefer:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
yt-transcriber                   # starts the web app
```

## Using the web app

1. Paste the YouTube link (`youtube.com/watch?v=…`, `youtu.be/…`, Shorts and live
   replays all work).
2. Pick the **spoken language**: *Auto-detect*, *Chinese*, or *English*. Forcing the
   language is a little faster and avoids wrong detection on videos with a long
   musical intro.
3. For Chinese videos, choose the **Chinese output** script: as spoken, Simplified or
   Traditional.
4. Pick a **Whisper model** (see the table below) and press **Transcribe**.
5. When it finishes, read the text, toggle timestamps, **Copy** it, or download
   `.txt`, `.srt`, `.vtt` or `.json`.

Your language, script and model choices are remembered in the browser.

## Downloading videos

Open the **Download** tab.

1. Paste a video link or a playlist link (`youtube.com/playlist?list=…`).
   A video link that also carries `&list=` is a video *inside* a playlist: tick
   **Download the whole playlist** to get all of it, leave it unticked for that one video.
2. Choose **Video (MP4)** with a maximum resolution, or **Audio only** as MP3 or M4A.
   1080p is the default: h264 MP4 that plays everywhere. "Best available" goes up to
   4K / 8K where YouTube offers it (VP9 / AV1 video).
3. Press **Download**. Playlists show "3/25" progress; when done you get the list of
   files, their sizes and an **Open folder** button.

Files are saved under `downloads/`; playlists get their own sub-folder named after the
playlist, with files numbered in playlist order. Videos that are already present are
not downloaded again, so re-running a playlist only fetches new uploads.

## Updating

Double-click `update.bat` (Windows) or run `./update.sh` (macOS / Linux) inside the app
folder. It downloads the latest version from GitHub, replaces the program files, and
reinstalls dependencies into the existing environment. Your `downloads`, `transcripts`
and settings are untouched.

## Command line

```bash
# Transcribe one video with defaults (auto-detect language, "small" model, txt + srt)
yt-transcriber https://www.youtube.com/watch?v=dQw4w9WgXcQ

# Chinese video, Simplified output, better model, all formats, custom folder
yt-transcriber transcribe https://youtu.be/VIDEO_ID -l zh -s simplified -m large-v3-turbo \
    -f txt,srt,vtt,json -o ~/Documents/transcripts

# Several videos in one go; print each transcript to the terminal as well
yt-transcriber URL1 URL2 URL3 --print

# Download a video as 1080p MP4 (the default), or as MP3
yt-transcriber download https://youtu.be/VIDEO_ID
yt-transcriber download https://youtu.be/VIDEO_ID --audio

# Download a whole playlist at up to 720p into a folder of your choice
yt-transcriber download "https://www.youtube.com/playlist?list=PL..." -q 720 -o ~/Videos

# Start the web app on another port without opening a browser
yt-transcriber serve --port 9000 --no-browser
```

Run `yt-transcriber transcribe --help` or `yt-transcriber download --help` for every option.

## Choosing a model

| Model            | Download | Speed on a laptop CPU            | Quality                                   |
|------------------|----------|----------------------------------|-------------------------------------------|
| `tiny`           | 75 MB    | very fast                        | rough; English only really usable         |
| `base`           | 150 MB   | fast                             | basic                                     |
| `small` (default)| 500 MB   | roughly real time                | good English, acceptable Chinese          |
| `medium`         | 1.5 GB   | several times slower than real time | noticeably better Chinese              |
| `large-v3`       | 3 GB     | impractical without a GPU        | best                                      |
| `large-v3-turbo` | 1.6 GB   | slow but usable on a fast CPU    | close to large-v3, much faster            |

For Chinese, `medium` or `large-v3-turbo` are worth the wait. With a GPU, use `large-v3-turbo`.

## Configuration

Environment variables, all optional:

| Variable                               | Default        | Meaning                                                   |
|----------------------------------------|----------------|-----------------------------------------------------------|
| `YT_TRANSCRIBER_MODEL`                 | `small`        | Default Whisper model in the web app and CLI              |
| `YT_TRANSCRIBER_OUTPUT_DIR`            | `transcripts`  | Where finished transcripts are saved                      |
| `YT_TRANSCRIBER_DOWNLOAD_DIR`          | `downloads`    | Where downloaded videos and audio are saved               |
| `YT_TRANSCRIBER_MODEL_DIR`             | HF cache       | Where downloaded Whisper models are stored                |
| `YT_TRANSCRIBER_DEVICE`                | `auto`         | `cpu`, `cuda`, or `auto` (GPU when available)             |
| `YT_TRANSCRIBER_COMPUTE_TYPE`          | `auto`         | `int8` on CPU, `float16` on GPU; override if needed       |
| `YT_TRANSCRIBER_COOKIES_FROM_BROWSER`  | unset          | `chrome`, `firefox`, `edge`, `safari`… see Troubleshooting |
| `YT_TRANSCRIBER_COOKIES_FILE`          | unset          | Netscape-format cookies file for yt-dlp                   |
| `YT_TRANSCRIBER_HOST` / `_PORT`        | `127.0.0.1` / `8000` | Where the web app listens                           |

## Troubleshooting

**"Sign in to confirm you're not a bot"** – YouTube sometimes refuses anonymous
downloads. Let yt-dlp use the cookies of a browser where you are signed in to YouTube:

```bash
yt-transcriber URL --cookies-from-browser chrome
# or for the web app:
YT_TRANSCRIBER_COOKIES_FROM_BROWSER=chrome ./run.sh
```

**Downloads fail with an extractor error** – YouTube changes often; update yt-dlp with
`pip install -U yt-dlp` inside the virtual environment.

**It is slow** – Transcription on a CPU takes roughly as long as the video for `small`
and several times longer for `medium`. Pick a smaller model, force the language instead
of auto-detecting, or use a GPU.

**Wrong Chinese script** – Whisper decides Simplified or Traditional on its own. Set
**Chinese output** to the script you want; the app converts the result.

**Repeated or hallucinated lines** – Whisper sometimes loops on silence or music. The
app already filters silence with VAD; trying a larger model usually fixes the rest.

**The window closes at once (Windows)** – `run.bat` pauses and shows the reason when
something fails. If it still vanishes, open PowerShell in the folder and run `.\run.bat`
to read the message. The usual cause is Python not being installed or not on PATH.

**ffmpeg not found** – Install it (see Requirements). Without it transcription falls back
to a built-in decoder, video downloads are limited to 720p single-file streams, and audio
downloads stay M4A instead of being converted to MP3.

**A playlist shows "N failed"** – Those videos are private, removed, age-restricted or
region-locked. The rest of the playlist is downloaded anyway; the failure messages are
listed under the file list. Cookies (see above) fix the age-restricted ones.

### GPU

faster-whisper uses CUDA 12 and cuDNN 9. On Linux the easiest way to get the libraries is

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

and to make sure their `lib` folders are on `LD_LIBRARY_PATH` (see the faster-whisper
README). On Windows, install the CUDA 12 toolkit and cuDNN 9 from NVIDIA. The app picks
the GPU automatically when it is usable; the web app shows "GPU detected" under the
Transcribe button.

## How it works

```
transcribe: link ──▶ yt-dlp (best audio) ──▶ ffmpeg (16 kHz mono PCM) ──▶ faster-whisper ──▶ zhconv ──▶ txt / srt / vtt / json
download:   link ──▶ yt-dlp (video+audio streams or audio only) ──▶ ffmpeg (merge to MP4 / convert to MP3) ──▶ downloads/
```

- `yt_transcriber/urls.py` recognises YouTube links and extracts the video id.
- `yt_transcriber/downloader.py` fetches the audio-only stream with yt-dlp.
- `yt_transcriber/audio.py` decodes it to the PCM array Whisper expects.
- `yt_transcriber/transcriber.py` loads a cached faster-whisper model and streams segments.
- `yt_transcriber/zh.py` nudges Whisper toward the wanted Chinese script and converts the result.
- `yt_transcriber/pipeline.py` strings these together with progress reporting.
- `yt_transcriber/video_downloader.py` downloads videos, audio and playlists with yt-dlp,
  turning its hooks into progress and collecting the finished files and failures.
- `yt_transcriber/jobs.py` is a queue with one worker per job kind; `server.py` exposes it
  over HTTP for the page in `static/index.html`; `cli.py` drives both from the terminal.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests exercise everything except YouTube itself and the model download: Whisper is
replaced with a fake, audio decoding is tested against ffmpeg-generated files, and the
downloader is run for real with yt-dlp against a clip served from a local HTTP server.
