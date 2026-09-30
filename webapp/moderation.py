"""Модерация: отправка жалоб в Discord-канал через webhook."""

import json
import logging
import os
import urllib.request

from .db import DB, now

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_MENTION = os.getenv("DISCORD_MENTION", "")  # напр. <@123456789>

RED = 0xE74C3C


def _post_webhook(payload: dict) -> bool:
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL не задан — жалоба сохранена только в БД")
        return False
    try:
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        logger.exception("Не удалось отправить жалобу в Discord")
        return False


def create_report(reporter_id: int, accused_id: int, chat_id: int,
                  reason: str, evidence: str) -> int:
    """Сохраняет жалобу и уведомляет Discord."""
    cur = DB.execute(
        "INSERT INTO reports (reporter_id, accused_id, chat_id, reason, evidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (int(reporter_id), int(accused_id), int(chat_id), reason, evidence, now()),
    )
    report_id = cur.lastrowid

    reporter = DB.one("SELECT anon_num FROM users WHERE tg_id = ?", (reporter_id,))
    accused = DB.one("SELECT anon_num FROM users WHERE tg_id = ?", (accused_id,))

    reporter_label = f"Аноним #{reporter['anon_num']}" if reporter else "неизвестно"
    accused_label = f"Аноним #{accused['anon_num']}" if accused else "неизвестно"

    content = "🚨 **Новая жалоба** " + (DISCORD_MENTION or "")
    embed = {
        "title": f"Жалоба #{report_id}",
        "color": RED,
        "fields": [
            {"name": "Кто пожаловался", "value": reporter_label, "inline": True},
            {"name": "На кого", "value": accused_label, "inline": True},
            {"name": "Причина", "value": reason or "не указана", "inline": False},
            {"name": "Доказательства", "value": (evidence or "—")[:1000], "inline": False},
            {"name": "Чат", "value": f"#{chat_id}", "inline": True},
        ],
        "footer": {"text": "Разбор — в админ-панели Mini App"},
    }
    _post_webhook({"content": content, "embeds": [embed]})
    return report_id


def list_reports(status: str = "new"):
    return DB.all(
        "SELECT r.*, "
        "  ra.anon_num AS reporter_anon, "
        "  aa.anon_num AS accused_anon "
        "FROM reports r "
        "LEFT JOIN users ra ON ra.tg_id = r.reporter_id "
        "LEFT JOIN users aa ON aa.tg_id = r.accused_id "
        "WHERE r.status = ? ORDER BY r.id DESC LIMIT 100",
        (status,),
    )


def resolve_report(report_id: int, status: str = "done"):
    DB.execute("UPDATE reports SET status = ? WHERE id = ?", (status, int(report_id)))


def ban_user(tg_id: int, reason: str = ""):
    DB.execute(
        "UPDATE users SET banned = 1, banned_reason = ? WHERE tg_id = ?",
        (reason, int(tg_id)),
    )
    # выкинуть из очереди и закрыть активный чат
    DB.execute("DELETE FROM queue WHERE tg_id = ?", (int(tg_id),))
    close_active_chats(int(tg_id))


def unban_user(tg_id: int):
    DB.execute(
        "UPDATE users SET banned = 0, banned_reason = NULL WHERE tg_id = ?",
        (int(tg_id),),
    )


def close_active_chats(tg_id: int):
    chats = DB.all(
        "SELECT id, user_a, user_b FROM chats WHERE status = 'active' "
        "AND (user_a = ? OR user_b = ?)",
        (tg_id, tg_id),
    )
    for chat in chats:
        close_chat(chat["id"])
    return chats


def close_chat(chat_id: int):
    """Закрывает чат, возвращает id второго участника (или None)."""
    chat = DB.one(
        "SELECT * FROM chats WHERE id = ? AND status = 'active'", (int(chat_id),)
    )
    if not chat:
        return None
    DB.execute(
        "UPDATE chats SET status = 'closed', closed_at = ? WHERE id = ?",
        (now(), int(chat_id)),
    )
    return chat
