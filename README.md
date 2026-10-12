# YouTube Transcriber

Paste a YouTube link, get a transcript. Works for **Chinese (中文)** and **English**,
with automatic language detection. Everything runs on your own computer: the audio is
fetched with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and transcribed with
[Whisper](https://github.com/openai/whisper) via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper). No API key, no cost per video.

Features

- Web app: paste a link, watch the progress bar, read, copy or download the transcript.
- Output as plain text, SRT or WebVTT subtitles, or JSON with timestamps.
- Chinese output can be forced to Simplified (简体) or Traditional (繁體).
- Queue several videos; they are transcribed one after another.
- Command line mode for scripting and batch jobs.
- Transcripts are also saved as files in a `transcripts` folder.

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

## Command line

```bash
# Transcribe one video with defaults (auto-detect language, "small" model, txt + srt)
yt-transcriber https://www.youtube.com/watch?v=dQw4w9WgXcQ

# Chinese video, Simplified output, better model, all formats, custom folder
yt-transcriber transcribe https://youtu.be/VIDEO_ID -l zh -s simplified -m large-v3-turbo \
    -f txt,srt,vtt,json -o ~/Documents/transcripts

# Several videos in one go; print each transcript to the terminal as well
yt-transcriber URL1 URL2 URL3 --print

# Start the web app on another port without opening a browser
yt-transcriber serve --port 9000 --no-browser
```

Run `yt-transcriber transcribe --help` for every option.

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

**ffmpeg not found** – Install it (see Requirements). Without it the app falls back to a
built-in decoder that handles most but not all files.

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
link ──▶ yt-dlp (best audio) ──▶ ffmpeg (16 kHz mono PCM) ──▶ faster-whisper ──▶ zhconv ──▶ txt / srt / vtt / json
```

- `yt_transcriber/urls.py` recognises YouTube links and extracts the video id.
- `yt_transcriber/downloader.py` fetches the audio-only stream with yt-dlp.
- `yt_transcriber/audio.py` decodes it to the PCM array Whisper expects.
- `yt_transcriber/transcriber.py` loads a cached faster-whisper model and streams segments.
- `yt_transcriber/zh.py` nudges Whisper toward the wanted Chinese script and converts the result.
- `yt_transcriber/pipeline.py` strings these together with progress reporting.
- `yt_transcriber/jobs.py` is a one-worker queue; `server.py` exposes it over HTTP for the
  page in `static/index.html`; `cli.py` drives the same pipeline from the terminal.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests exercise everything except the real network and model download: yt-dlp and
Whisper are replaced with fakes, audio decoding is tested against ffmpeg-generated files.
