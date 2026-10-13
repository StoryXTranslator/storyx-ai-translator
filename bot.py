
import os
import re
import asyncio
import tempfile
import subprocess
from pathlib import Path

import yt_dlp
from openai import OpenAI
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_KEY = os.environ["OPENAI_API_KEY"]

client = OpenAI(api_key=OPENAI_KEY)

URL_PATTERN = re.compile(
    r"https?://\S+"
    r"(youtube\.com|youtu\.be|tiktok\.com)\S*",
    re.IGNORECASE,
)


def summarize_video(video_path):
    """Extract audio, transcribe it, and summarize in Khmer."""
    with tempfile.TemporaryDirectory() as folder:
        audio_path = Path(folder) / "audio.mp3"

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vn", "-ac", "1", "-ar", "16000",
                "-b:a", "48k", str(audio_path),
            ],
            check=True,
            capture_output=True,
        )

        if audio_path.stat().st_size > 24 * 1024 * 1024:
            raise ValueError(
                "វីដេអូវែងពេក។ សូមកាត់ឱ្យខ្លីជាងនេះ។"
            )

        with open(audio_path, "rb") as audio:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
            )

        transcript = result.text.strip()

        if not transcript:
            return "ខ្ញុំមិនអាចស្គាល់សំឡេងក្នុងវីដេអូនេះបានទេ។"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "អ្នកជាអ្នកសម្រាយរឿងជាភាសាខ្មែរងាយយល់។ "
                        "សម្រាយរឿងពីអត្ថបទសំឡេងនេះជាភាសាខ្មែរ។ "
                        "បើជារឿងចិន សូមបកប្រែឈ្មោះនិងព្រឹត្តិការណ៍ "
                        "ឱ្យងាយយល់។ សរសេរចំណងជើង សាច់រឿង "
                        "និងចុងបញ្ចប់ ប្រសិនបើមានព័ត៌មានគ្រប់គ្រាន់។ "
                        "កុំប្រឌិតព័ត៌មានដែលមិនមានក្នុងអត្ថបទ។"
                    ),
                },
                {
                    "role": "user",
                    "content": transcript[:18000],
                },
            ],
            temperature=0.4,
        )

        return response.choices[0].message.content or (
            "សុំទោស ខ្ញុំមិនអាចសម្រាយរឿងនេះបានទេ។"
        )


def download_video(url, output_folder):
    options = {
        "format": "best[height<=720]/best",
        "outtmpl": str(Path(output_folder) / "video.%(ext)s"),
        "noplaylist": True,
        "max_filesize": 80 * 1024 * 1024,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        path = Path(downloader.prepare_filename(info))

        if not path.exists():
            files = list(Path(output_folder).glob("video.*"))
            if not files:
                raise ValueError("រកមិនឃើញឯកសារវីដេអូទេ។")
            path = files[0]

        return path


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "សួស្តី! ខ្ញុំជា AI Bot សម្រាយរឿងជាភាសាខ្មែរ។\n\n"
        "១. ផ្ញើវីដេអូមកខ្ញុំ\n"
        "២. ឬផ្ញើតំណ YouTube/TikTok សាធារណៈ\n"
        "៣. រង់ចាំខ្ញុំសម្រាយរឿងជាភាសាខ្មែរ។"
    )


async def process_and_reply(update, video_path):
    await update.message.reply_text(
        "ខ្ញុំកំពុងស្តាប់សំឡេង និងសម្រាយរឿង សូមរង់ចាំ..."
    )

    try:
        summary = await asyncio.to_thread(
            summarize_video, video_path
        )

        # Telegram messages have a length limit.
        for start in range(0, len(summary), 4000):
            await update.message.reply_text(summary[start:start + 4000])

    except Exception as error:
        print("Processing error:", repr(error))
        await update.message.reply_text(
            "សុំទោស! មិនអាចដំណើរការវីដេអូនេះបានទេ។ "
            "សូមសាកល្បងវីដេអូខ្លីជាងនេះ ឬតំណសាធារណៈផ្សេងទៀត។"
        )


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video or update.message.document

    if not video:
        return

    if video.file_size and video.file_size > 20 * 1024 * 1024:
        await update.message.reply_text(
            "វីដេអូធំពេកសម្រាប់ការទាញយកតាម Bot API នេះ។ "
            "សូមផ្ញើវីដេអូតូចជាង 20 MB។"
        )
        return

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "uploaded_video.mp4"
        telegram_file = await context.bot.get_file(video.file_id)
        await telegram_file.download_to_drive(path)

        await process_and_reply(update, path)


async def link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    match = URL_PATTERN.search(text)

    if not match:
        await update.message.reply_text(
            "សូមផ្ញើវីដេអូ ឬតំណ YouTube/TikTok សាធារណៈ។"
        )
        return

    url = match.group(0).rstrip(".,!?)]}")

    await update.message.reply_text(
        "ខ្ញុំកំពុងព្យាយាមទាញយកវីដេអូ សូមរង់ចាំ..."
    )

    try:
        with tempfile.TemporaryDirectory() as folder:
            path = await asyncio.to_thread(
                download_video, url, folder
            )
            await process_and_reply(update, path)

    except Exception as error:
        print("Download error:", repr(error))
        await update.message.reply_text(
            "ខ្ញុំមិនអាចបើកតំណនេះបានទេ។ "
            "វីដេអូអាចជាឯកជន ត្រូវការចូលគណនី "
            "ឬមិនអាចទាញយកបាន។ សូមសាកល្បងតំណសាធារណៈ "
            "ឬផ្ញើឯកសារវីដេអូដោយផ្ទាល់។"
        )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(
            filters.VIDEO
            | filters.Document.MimeType("video/mp4")
            | filters.Document.MimeType("video/quicktime"),
            video_handler,
        )
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, link_handler)
    )

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
