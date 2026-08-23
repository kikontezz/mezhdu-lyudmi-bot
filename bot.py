import os
import logging
from threading import Thread

from flask import Flask

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# =========================
# ЛОГИ
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# НАСТРОЙКИ
# =========================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))


# =========================
# FLASK
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Между людьми — бот работает!"


@app.route("/healthz")
def healthz():
    return "OK"


# =========================
# TELEGRAM КОМАНДЫ
# =========================

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


async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "Сообщение получено.\n\n"
        "Поиск собеседника пока находится в разработке."
    )


# =========================
# FLASK SERVER
# =========================

def run_web_server():
    app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False,
    )


# =========================
# ЗАПУСК БОТА
# =========================

def main():

    if not TOKEN:
        raise RuntimeError(
            "Не найден BOT_TOKEN. "
            "Добавь BOT_TOKEN в Environment Variables Render."
        )

    # Запускаем Flask в отдельном потоке
    web_thread = Thread(
        target=run_web_server,
        daemon=True,
    )

    web_thread.start()

    # Создаём Telegram Application
    application = (
        Application.builder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(30)
        .get_updates_pool_timeout(30)
        .build()
    )

    # Команды
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("rules", rules)
    )

    application.add_handler(
        CommandHandler("about", about)
    )

    # Обычные текстовые сообщения
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler,
        )
    )

    print("Бот запускается...")

    # Запускаем polling
    application.run_polling(
        drop_pending_updates=True,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
