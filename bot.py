import os
import logging
from threading import Thread

from flask import Flask, send_from_directory

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# URL твоего Render-сервиса
WEB_APP_URL = os.getenv(
    "WEB_APP_URL",
    "https://mezhdu-lyudmi-bot.onrender.com",
)

app = Flask(__name__)


@app.route("/")
def home():
    return send_from_directory("web", "index.html")


@app.route("/healthz")
def healthz():
    return "OK"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton(
                "💬 Открыть «Между людьми»",
                web_app=WebAppInfo(url=WEB_APP_URL),
            )
        ]
    ]

    await update.message.reply_text(
        "👋 Добро пожаловать в «Между людьми»!\n\n"
        "Это анонимное приложение для общения один-на-один.\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def run_web_server():
    app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False,
    )


def main():
    if not TOKEN:
        raise RuntimeError("Не найден BOT_TOKEN")

    Thread(
        target=run_web_server,
        daemon=True,
    ).start()

    application = Application.builder().token(TOKEN).build()

    application.add_handler(
        CommandHandler("start", start)
    )

    print("Бот запускается...")

    application.run_polling(
        drop_pending_updates=True,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
