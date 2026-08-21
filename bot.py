import os
import logging

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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Это «Между людьми» — анонимный чат, где можно "
        "пообщаться с другим человеком.\n\n"
        "Здесь никто не видит твоё имя и профиль собеседника.\n\n"
        "Перед началом обязательно ознакомься с правилами.\n\n"
        "Команды:\n"
        "/start — начать\n"
        "/help — помощь\n"
        "/rules — правила\n"
        "/about — о боте"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Доступные команды:\n\n"
        "/start — начать работу с ботом\n"
        "/help — помощь\n"
        "/rules — правила\n"
        "/about — информация о боте"
    )


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Правила:\n\n"
        "1. Уважай собеседника.\n"
        "2. Не публикуй личные данные.\n"
        "3. Не отправляй запрещённый или опасный контент.\n"
        "4. Не угрожай другим пользователям.\n"
        "5. При нарушении правил используй жалобу.\n\n"
        "Возраст: 14+."
    )


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ О боте\n\n"
        "«Между людьми» — анонимный Telegram-бот "
        "для общения один-на-один.\n\n"
        "На следующем этапе мы добавим поиск собеседника, "
        "анонимную передачу сообщений, завершение диалога "
        "и систему жалоб."
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Сообщение получено.\n\n"
        "Система поиска собеседника пока находится в разработке."
    )


def main():
    if not TOKEN:
        raise RuntimeError("Не найден BOT_TOKEN")

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("rules", rules))
    application.add_handler(CommandHandler("about", about))

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    print("Бот запущен!")
    application.run_polling()


if __name__ == "__main__":
    main()
