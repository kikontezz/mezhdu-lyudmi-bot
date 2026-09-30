"""Локальный веб-сервер для разработки UI без Telegram.

Запуск: python tests/run_web.py
Открыть: http://localhost:8899  (первый «пользователь»)
         http://localhost:8899/?dev=222 (второй, для проверки чата)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "123456:DEV-TEST")
os.environ.setdefault("DEV_FAKE_AUTH", "1")
os.environ.setdefault("PORT", "8899")
os.environ.setdefault("ADMIN_IDS", "111")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/opencode/dev.db")

from webapp.db import init_db  # noqa: E402

init_db()

from bot import app  # noqa: E402

if __name__ == "__main__":
    print("http://localhost:8899  (dev:111, админ)")
    print("http://localhost:8899/?dev=222  (dev:222)")
    app.run(host="0.0.0.0", port=8899, debug=False, threaded=True)
