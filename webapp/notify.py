"""Очередь уведомлений в Telegram: складываем в БД, фоновый поток отправляет.

force=1 — отправлять всегда (важные события).
force=0 — отправлять только если пользователь не открывал приложение больше 2 минут
(иначе он и так видит сообщения в открытом чате).
"""

import logging
import threading
import time

from .db import DB, now

logger = logging.getLogger(__name__)

IDLE_SECONDS = 120

_bot = None
_started = False


def set_bot(bot):
    global _bot
    _bot = bot


def push(tg_id: int, text: str, force: bool = True):
    """Поставить уведомление в очередь."""
    try:
        DB.execute(
            "INSERT INTO notifications (tg_id, text, force, created_at) "
            "VALUES (?, ?, ?, ?)",
            (int(tg_id), text, 1 if force else 0, now()),
        )
    except Exception:
        logger.exception("Не удалось сохранить уведомление")


def touch(tg_id: int):
    """Отметить, что пользователь сейчас в приложении."""
    try:
        DB.execute(
            "UPDATE users SET last_seen_at = ? WHERE tg_id = ?",
            (now(), int(tg_id)),
        )
    except Exception:
        pass


def _sender_loop():
    while True:
        try:
            rows = DB.all(
                "SELECT n.id, n.tg_id, n.text, n.force, u.last_seen_at "
                "FROM notifications n "
                "LEFT JOIN users u ON u.tg_id = n.tg_id "
                "WHERE n.sent = 0 ORDER BY n.id LIMIT 20"
            )
            for row in rows:
                send = True
                if not row["force"]:
                    last = row.get("last_seen_at") or 0
                    send = (now() - last) > IDLE_SECONDS
                if send and _bot is not None:
                    try:
                        _bot.send_message(chat_id=row["tg_id"], text=row["text"])
                    except Exception as exc:
                        logger.info("Уведомление не отправлено: %s", exc)
                        continue
                DB.execute("UPDATE notifications SET sent = 1 WHERE id = ?", (row["id"],))
        except Exception:
            logger.exception("Ошибка фоновой отправки уведомлений")
        time.sleep(3)


def start_worker():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_sender_loop, daemon=True).start()
