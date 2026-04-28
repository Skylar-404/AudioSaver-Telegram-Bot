import logging
import os
import shutil
import asyncio
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import downloader  # your yt-dlp logic

# ─── Configuration ────────────────────────────────────────────────────────────

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in .env")

TELEGRAM_MAX_BYTES = 50 * 1024 * 1024  # 50MB

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _format_duration(seconds: int) -> str:
    if not seconds:
        return "unknown"
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _cleanup(path: Path) -> None:
    """Delete only the file (safe cleanup)."""
    try:
        if path and path.exists():
            path.unlink()
    except Exception:
        pass


# ─── Command Handlers ─────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "👋 <b>Welcome to YouTube Downloader Bot!</b>\n\n"
        "Use <code>/dl &lt;YouTube URL&gt;</code> to download a video.\n"
        "You'll get buttons to choose MP4 or MP3.\n\n"
        "Type /help for more details.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "📖 <b>How to use:</b>\n\n"
        "<code>/dl &lt;YouTube URL&gt;</code>\n\n"
        "The bot will fetch video info and show buttons:\n"
        "• 🎬 <b>MP4</b> — video\n"
        "• 🎵 <b>MP3</b> — audio\n\n"
        "⚠️ Max file size: 50MB\n"
        "⚠️ ffmpeg must be installed",
        parse_mode=ParseMode.HTML,
    )


async def cmd_dl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Provide a URL.\nUsage: <code>/dl &lt;YouTube URL&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    url = context.args[0].strip()
    status_msg = await update.message.reply_text("🔍 Fetching video info...")

    try:
        info = downloader.get_video_info(url)
    except Exception as exc:
        logger.exception("Info fetch failed")
        await status_msg.edit_text(f"❌ Failed:\n<code>{str(exc)}</code>", parse_mode=ParseMode.HTML)
        return

    title = info.get("title", "Unknown")
    uploader = info.get("uploader", "Unknown")
    duration = _format_duration(info.get("duration"))

    key = str(status_msg.message_id)
    context.user_data[key] = url  # safer than bot_data

    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🎬 MP4", callback_data=f"mp4|{key}"),
            InlineKeyboardButton("🎵 MP3", callback_data=f"mp3|{key}")
        ]]
    )

    await status_msg.edit_text(
        f"🎬 <b>{title}</b>\n"
        f"👤 {uploader} | ⏱ {duration}\n\n"
        "Choose format:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ─── Callback Handler ─────────────────────────────────────────────────────────


async def callback_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if not query or not query.message:
        return

    await query.answer()

    try:
        fmt, key = query.data.split("|", 1)
    except Exception:
        await query.edit_message_text("❌ Invalid request.")
        return

    url = context.user_data.get(key)

    if not url:
        await query.edit_message_text("❌ Session expired. Use /dl again.")
        return

    fmt_label = "MP4 🎬" if fmt == "mp4" else "MP3 🎵"

    await query.edit_message_text(f"⏳ Downloading {fmt_label}...")

    file_path: Optional[Path] = None

    try:
        # run blocking download in thread
        file_path = await asyncio.to_thread(
            downloader.download_video if fmt == "mp4" else downloader.download_audio,
            url
        )

        if not file_path or not file_path.exists():
            raise RuntimeError("Download failed (no file)")

        size_mb = file_path.stat().st_size / 1024 / 1024

        if file_path.stat().st_size > TELEGRAM_MAX_BYTES:
            await query.edit_message_text(
                f"❌ File too large ({size_mb:.1f} MB > 50 MB)"
            )
            return

        await query.edit_message_text(f"📤 Sending {fmt_label}...")

        chat_id = query.message.chat.id

        with open(file_path, "rb") as f:
            if fmt == "mp4":
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=f,
                    filename=file_path.name,
                    caption=f"🎬 {file_path.stem}",
                    supports_streaming=True,
                )
            else:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    filename=file_path.name,
                    caption=f"🎵 {file_path.stem}",
                )

        await query.edit_message_text(f"✅ {fmt_label} sent!")

    except Exception as exc:
        logger.exception("Download/send failed")
        await query.edit_message_text(
            f"❌ Failed:\n<code>{str(exc)}</code>",
            parse_mode=ParseMode.HTML,
        )

    finally:
        if file_path:
            _cleanup(file_path)
        context.user_data.pop(key, None)


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("dl", cmd_dl))
    app.add_handler(CallbackQueryHandler(callback_download))

    logger.info("Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
