import os
import logging

from flask import Flask
from threading import Thread

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

app = Flask(__name__)


@app.route("/")
def home():
    return "Между людьми — бот работает!"


@app.route("/healthz")
def healthz():
    return "OK"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Это «Между людьми» — анонимный чат.\n\n"
        "Здесь можно будет найти собеседника "
        "и общаться анонимно.\n\n"
        "Команды:\n"
        "/start — начать\n"
        "/help — помощь\n"
        "/rules — правила\n"
        "/about — о боте"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Доступные команды:\n\n"
        "/start — начать\n"
        "/help — помощь\n"
        "/rules — правила\n"
        "/about — о боте"
    )


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Правила:\n\n"
        "1. Уважай собеседника.\n"
        "2. Не публикуй личные данные.\n"
        "3. Не отправляй опасный или запрещённый контент.\n"
        "4. Не угрожай другим пользователям.\n"
        "5. При нарушении правил используй жалобу.\n\n"
        "Возраст: 14+."
    )


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ «Между людьми» — анонимный Telegram-бот "
        "для общения один-на-один."
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Сообщение получено.\n\n"
        "Поиск собеседника пока находится в разработке."
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

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(CommandHandler("about", about))

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler,
        )
    )

    print("Бот запущен!")
    application.run_polling()


if __name__ == "__main__":
    main()
