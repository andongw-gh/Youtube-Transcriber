"""Command line entry point: `yt-transcriber` (web app) and `yt-transcriber transcribe URL…`."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import Settings
from .formats import FORMATS, output_basename, write_outputs
from .pipeline import STAGE_LABELS, TranscribeOptions
from .pipeline import run as run_pipeline
from .transcriber import DEVICE_CHOICES, LANGUAGE_CHOICES, MODEL_CHOICES
from .zh import SCRIPT_CHOICES

COMMANDS = ("transcribe", "serve")


def build_parser(settings: Settings | None = None) -> argparse.ArgumentParser:
    settings = settings or Settings.from_env()
    parser = argparse.ArgumentParser(
        prog="yt-transcriber",
        description="Transcribe YouTube videos (Chinese / English) locally with Whisper.",
        epilog="Run with no arguments to start the web app. "
        "A bare URL is a shortcut for `transcribe URL`.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true", help="Show debug logging")

    sub = parser.add_subparsers(dest="command", metavar="command")

    tr = sub.add_parser("transcribe", parents=[common], help="Transcribe one or more videos from the terminal")
    tr.add_argument("urls", nargs="+", metavar="URL", help="YouTube video link(s)")
    tr.add_argument("-l", "--language", choices=LANGUAGE_CHOICES, default="auto",
                    help="Spoken language (default: auto-detect)")
    tr.add_argument("-m", "--model", choices=MODEL_CHOICES, default=settings.default_model,
                    help=f"Whisper model (default: {settings.default_model})")
    tr.add_argument("-s", "--chinese-script", choices=SCRIPT_CHOICES, default="keep",
                    help="Convert Chinese output to simplified or traditional (default: keep)")
    tr.add_argument("-f", "--formats", default="txt,srt",
                    help=f"Comma-separated output formats from {','.join(FORMATS)} (default: txt,srt)")
    tr.add_argument("-o", "--output-dir", type=Path, default=settings.output_dir,
                    help=f"Where to write transcripts (default: {settings.output_dir})")
    tr.add_argument("--device", choices=DEVICE_CHOICES, default=settings.device,
                    help="Run Whisper on cpu or cuda (default: auto)")
    tr.add_argument("--model-dir", default=str(settings.model_dir) if settings.model_dir else None,
                    help="Directory to cache downloaded Whisper models")
    tr.add_argument("--cookies-from-browser", default=settings.cookies_from_browser, metavar="BROWSER",
                    help="Use cookies from chrome/firefox/edge/safari when YouTube asks you to sign in")
    tr.add_argument("--cookies-file", default=settings.cookies_file, metavar="FILE",
                    help="Netscape-format cookies file for yt-dlp")
    tr.add_argument("--beam-size", type=int, default=5, help="Whisper beam size (default: 5)")
    tr.add_argument("-p", "--print", dest="print_text", action="store_true",
                    help="Also print the transcript to stdout")
    tr.set_defaults(func=cmd_transcribe)

    sv = sub.add_parser("serve", parents=[common], help="Start the local web app (default command)")
    sv.add_argument("--host", default=settings.host, help=f"Bind address (default: {settings.host})")
    sv.add_argument("--port", type=int, default=settings.port, help=f"Port (default: {settings.port})")
    sv.add_argument("-o", "--output-dir", type=Path, default=settings.output_dir,
                    help=f"Where finished transcripts are saved (default: {settings.output_dir})")
    sv.add_argument("--no-browser", action="store_true", help="Don't open the browser automatically")
    sv.set_defaults(func=cmd_serve)
    return parser


class ConsoleProgress:
    """Single-line progress display for the terminal."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stderr
        self._stage: str | None = None

    def __call__(self, stage: str, fraction: float | None, message: str) -> None:
        if stage != self._stage:
            if self._stage is not None:
                self.stream.write("\n")
            self._stage = stage
        label = STAGE_LABELS.get(stage, stage)
        pct = f"{fraction * 100:5.1f}%" if fraction is not None else "  …   "
        line = f"\r  {label:<14}{pct}  {message[:72]}"
        self.stream.write(line.ljust(110))
        self.stream.flush()

    def finish(self) -> None:
        if self._stage is not None:
            self.stream.write("\n")
            self.stream.flush()
        self._stage = None


def _parse_formats(raw: str) -> list[str]:
    formats = [part.strip().lower().lstrip(".") for part in raw.split(",") if part.strip()]
    unknown = [fmt for fmt in formats if fmt not in FORMATS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"Unknown format(s): {', '.join(unknown)}. Choose from {', '.join(FORMATS)}."
        )
    return formats or ["txt"]


def cmd_transcribe(args: argparse.Namespace) -> int:
    try:
        formats = _parse_formats(args.formats)
    except argparse.ArgumentTypeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    options = TranscribeOptions(
        language=args.language,
        model=args.model,
        chinese_script=args.chinese_script,
        device=args.device,
        model_dir=args.model_dir,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies_file,
        beam_size=args.beam_size,
    )
    try:
        options.validate()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    failures = 0
    for url in args.urls:
        print(f"▶ {url}")
        progress = ConsoleProgress()
        try:
            transcript = run_pipeline(url, options, progress=progress)
        except KeyboardInterrupt:
            progress.finish()
            print("Interrupted.", file=sys.stderr)
            return 130
        except Exception as exc:  # noqa: BLE001 - report and continue with the next URL
            progress.finish()
            print(f"✖ Failed: {exc}", file=sys.stderr)
            if args.verbose:
                logging.getLogger(__name__).exception("Transcription failed for %s", url)
            failures += 1
            continue
        progress.finish()

        basename = output_basename(transcript.title, transcript.video_id)
        paths = write_outputs(args.output_dir, basename, transcript.segments, transcript.language,
                              transcript.metadata(), formats)
        print(f"✔ {transcript.title}")
        print(f"  language: {transcript.language} ({transcript.language_probability:.0%})"
              f"   duration: {transcript.duration / 60:.1f} min   model: {transcript.model}")
        for path in paths:
            print(f"  saved: {path}")
        if args.print_text:
            print()
            print(transcript.text)
            print()
    return 1 if failures else 0


def cmd_serve(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    settings.host = args.host
    settings.port = args.port
    settings.output_dir = args.output_dir
    from .server import serve

    try:
        serve(settings, open_browser=not args.no_browser)
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["serve"]
    elif argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv = ["transcribe", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
