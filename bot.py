
from __future__ import annotations

import asyncio
import logging
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    TELEGRAM_BOT_TOKEN,
    PORT,
    MAX_VIDEO_MB,
    MAX_VIDEO_SECONDS,
    MAX_OUTPUT_MB,
    PROCESSING_TIMEOUT_SECONDS,
    MAX_CONCURRENT_PROCESSING,
    WELCOME_TEXT,
    HELP_TEXT,
)

from audio_processor import (
    InputValidationError,
    MediaProcessingError,
    process_video,
)


LOGGER = logging.getLogger("noise_remover_bot")

PROCESSING_SLOT = asyncio.Semaphore(
    MAX_CONCURRENT_PROCESSING
)


class HealthHandler(BaseHTTPRequestHandler):
    """Tiny HTTP endpoint so the bot can run as a Web Service (port binding + uptime pings)."""

    def do_GET(self) -> None:  # noqa: N802
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()

    def log_message(self, format, *args) -> None:  # silence per-request logs
        return


def start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(
        target=server.serve_forever,
        name="health-server",
        daemon=True,
    ).start()
    LOGGER.info("Health server listening on port %s", port)
    return server


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del context

    if update.message:
        await update.message.reply_text(WELCOME_TEXT)


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del context

    if update.message:
        await update.message.reply_text(HELP_TEXT)


def uploaded_video(message):
    if message.video:
        return message.video, ".mp4"

    document = message.document

    if document and document.mime_type:
        if document.mime_type.startswith("video/"):
            extension = Path(
                document.file_name or ""
            ).suffix.lower()

            if extension not in {
                ".mp4",
                ".mov",
                ".mkv",
                ".webm",
                ".avi",
                ".m4v",
            }:
                extension = ".video"

            return document, extension

    return None, None


async def processing_updates(
    status_message,
    done: asyncio.Event,
) -> None:
    started = time.monotonic()

    while not done.is_set():
        try:
            await asyncio.wait_for(
                done.wait(),
                timeout=30,
            )
            return

        except asyncio.TimeoutError:
            elapsed = int(time.monotonic() - started)
            minutes, seconds = divmod(elapsed, 60)

            try:
                await status_message.edit_text(
                    "ভিডিও প্রসেস হচ্ছে: "
                    f"{minutes} মিনিট {seconds} সেকেন্ড।"
                )
            except TelegramError:
                # e.g. "message is not modified" or a flood limit: keep going.
                continue


async def safe_edit(status_message, text: str) -> None:
    try:
        await status_message.edit_text(text)
    except TelegramError:
        LOGGER.debug("Could not edit status message", exc_info=True)


async def handle_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = update.message

    if not message:
        return

    uploaded, extension = uploaded_video(message)

    if uploaded is None:
        await message.reply_text("একটি ভিডিও পাঠান।")
        return

    max_input_bytes = MAX_VIDEO_MB * 1024 * 1024
    file_size = uploaded.file_size or 0

    if file_size > max_input_bytes:
        await message.reply_text(
            f"ভিডিওটি {MAX_VIDEO_MB} MB সীমার চেয়ে বড়।"
        )
        return

    duration = getattr(uploaded, "duration", None)

    if duration and duration > MAX_VIDEO_SECONDS:
        await message.reply_text(
            f"ভিডিওটি {MAX_VIDEO_SECONDS} সেকেন্ডের চেয়ে বড়।"
        )
        return

    status_message = await message.reply_text(
        "ভিডিও গ্রহণ করা হয়েছে। প্রসেসিংয়ের জন্য অপেক্ষা করুন…"
    )

    await PROCESSING_SLOT.acquire()

    try:
        await safe_edit(status_message, "ভিডিও ডাউনলোড করা হচ্ছে…")

        with tempfile.TemporaryDirectory(
            prefix="noise-remover-"
        ) as temp_dir:

            work_dir = Path(temp_dir)

            input_path = work_dir / f"input{extension}"

            output_path = (
                work_dir / "video-without-background-music.mp4"
            )

            telegram_file = await context.bot.get_file(
                uploaded.file_id
            )

            await telegram_file.download_to_drive(
                custom_path=str(input_path)
            )

            await status_message.edit_text(
                "AI দিয়ে ব্যাকগ্রাউন্ড মিউজিক কমানো হচ্ছে…"
            )

            done = asyncio.Event()

            progress_task = asyncio.create_task(
                processing_updates(status_message, done)
            )

            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        process_video,
                        input_path,
                        output_path,
                        max_input_bytes=max_input_bytes,
                        max_duration_seconds=MAX_VIDEO_SECONDS,
                        max_output_bytes=MAX_OUTPUT_MB * 1024 * 1024,
                        timeout_seconds=PROCESSING_TIMEOUT_SECONDS,
                    ),
                    timeout=PROCESSING_TIMEOUT_SECONDS + 30,
                )

            finally:
                done.set()
                await progress_task

            await status_message.edit_text(
                "প্রসেস সম্পন্ন। ভিডিও পাঠানো হচ্ছে…"
            )

            with output_path.open("rb") as processed_video:
                await context.bot.send_video(
                    chat_id=message.chat_id,
                    video=processed_video,
                    supports_streaming=True,
                    caption="ব্যাকগ্রাউন্ড মিউজিক কমানো ভিডিও",
                    read_timeout=120,
                    write_timeout=120,
                )

            await status_message.edit_text(
                "ভিডিও পাঠানো হয়েছে।"
            )

    except InputValidationError as exc:
        await safe_edit(status_message, str(exc))

    except (
        MediaProcessingError,
        TelegramError,
        OSError,
        TimeoutError,
    ):
        LOGGER.exception("Video processing or delivery failed")

        try:
            await status_message.edit_text(
                "ভিডিও প্রসেস করা যায়নি। "
                "ছোট MP4 ভিডিও দিয়ে আবার চেষ্টা করুন।"
            )
        except TelegramError:
            pass

    except Exception:
        LOGGER.exception("Unexpected video processing error")

        try:
            await status_message.edit_text(
                "অপ্রত্যাশিত সমস্যা হয়েছে। "
                "কিছুক্ষণ পরে আবার চেষ্টা করুন।"
            )
        except TelegramError:
            pass

    finally:
        PROCESSING_SLOT.release()


async def handle_other_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    del context

    if update.message:
        await update.message.reply_text(
            "ভিডিও পাঠান অথবা /help লিখুন।"
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO level, which contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN environment variable সেট করুন।"
        )

    # Bind the HTTP port first so the platform sees the service as live.
    start_health_server(PORT)

    application: Application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(4)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(120)
        .media_write_timeout(180)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(
            filters.VIDEO | filters.Document.VIDEO,
            handle_video,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_other_message,
        )
    )

    LOGGER.info("Telegram noise-removal bot is starting")

    application.run_polling(
        allowed_updates=["message"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
