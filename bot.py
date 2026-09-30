import logging
import os
from threading import Thread

from flask import Flask, send_from_directory

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

from webapp import notify
from webapp.api import api
from webapp.db import init_db
from webapp.discord_bot import start as start_discord_bot

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# URL твоего Render-сервиса (для кнопки Mini App)
WEB_APP_URL = os.getenv(
    "WEB_APP_URL",
    "https://mezhdu-lyudmi-bot.onrender.com",
)

app = Flask(__name__, static_folder="web", static_url_path="/static")
app.register_blueprint(api)


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
        "Это анонимное общение один-на-один: "
        "без имён, без ников — только ты, собеседник и аватарка.\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def run_web_server():
    app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False,
        threaded=True,
    )


def main():
    if not TOKEN:
        raise RuntimeError("Не найден BOT_TOKEN")

    init_db()
    logger.info("База данных готова")

    Thread(target=run_web_server, daemon=True).start()

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    notify.set_bot(application.bot)
    notify.start_worker()

    # Discord-бот для жалоб (если задан DISCORD_BOT_TOKEN)
    start_discord_bot()

    print("Бот запускается...")

    application.run_polling(
        drop_pending_updates=True,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
