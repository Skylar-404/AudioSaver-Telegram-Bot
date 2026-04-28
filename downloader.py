import os
import re
import tempfile
from pathlib import Path
import yt_dlp


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_tempdir() -> str:
    return tempfile.mkdtemp(prefix="ytdl_")


def _safe_filename(name: str) -> str:
    """Sanitize filename to avoid OS issues."""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip()[:80]


def _find_file(tmpdir: str, ext: str) -> Path:
    """Find the correct output file by extension."""
    files = list(Path(tmpdir).glob(f"*.{ext}"))
    if not files:
        raise FileNotFoundError(f"No .{ext} file found after download.")
    return files[0]


# ─── Video Download ───────────────────────────────────────────────────────────

def download_video(url: str) -> Path:
    tmpdir = _make_tempdir()
    output_template = os.path.join(tmpdir, "%(title).80s.%(ext)s")

    ydl_opts = {
        "format": "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        file_path = _find_file(tmpdir, "mp4")

        # Rename safely
        safe_name = _safe_filename(file_path.stem) + ".mp4"
        safe_path = file_path.with_name(safe_name)
        file_path.rename(safe_path)

        return safe_path

    except Exception as e:
        raise RuntimeError(f"Video download failed: {e}")


# ─── Audio Download ───────────────────────────────────────────────────────────

def download_audio(url: str) -> Path:
    tmpdir = _make_tempdir()
    output_template = os.path.join(tmpdir, "%(title).80s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        file_path = _find_file(tmpdir, "mp3")

        safe_name = _safe_filename(file_path.stem) + ".mp3"
        safe_path = file_path.with_name(safe_name)
        file_path.rename(safe_path)

        return safe_path

    except Exception as e:
        raise RuntimeError(f"Audio download failed: {e}")


# ─── Metadata ─────────────────────────────────────────────────────────────────

def get_video_info(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        return {
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", "Unknown"),
        }

    except Exception as e:
        raise RuntimeError(f"Failed to fetch video info: {e}")
