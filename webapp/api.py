"""API Mini App: авторизация, профили, очередь, чат (long-polling), жалобы, админка."""

import base64
import os
import threading
import time

from flask import Blueprint, Response, jsonify, request

from .db import DB, now
from .moderation import (
    ban_user,
    close_active_chats,
    close_chat,
    create_report,
    list_reports,
    resolve_report,
    unban_user,
)
from . import notify
from .tg_auth import validate_init_data

api = Blueprint("api", __name__, url_prefix="/api")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip()
}

MAX_TEXT = 1000
MAX_AVATAR = 300_000  # base64-строка, байт не более ~220KB

# Режим локальной разработки: принимаем initData вида "dev:<tg_id>" без подписи.
# На проде НЕ задавать (BOT_TOKEN окружения на Render без DEV_FAKE_AUTH).
DEV_FAKE = os.getenv("DEV_FAKE_AUTH") == "1"

_match_lock = threading.Lock()

# «печатает...»: (chat_id, tg_id) -> время последнего нажатия
_typing_times: dict = {}
TYPING_TTL = 4  # секунд


# --------------------------------------------------------------------------
# утилиты
# --------------------------------------------------------------------------

def _is_admin(tg_id: int) -> bool:
    return int(tg_id) in ADMIN_IDS


def _public_user(u: dict) -> dict:
    return {
        "tg_id": u["tg_id"],
        "anon_num": u["anon_num"],
        "avatar": u.get("avatar"),
        "banned": bool(u.get("banned")),
        "notify": bool(u.get("notify", 1)),
        "is_admin": _is_admin(u["tg_id"]),
    }


def _get_user(tg_id: int) -> dict | None:
    return DB.one("SELECT * FROM users WHERE tg_id = ?", (tg_id,))


def _active_chat(tg_id: int) -> dict | None:
    return DB.one(
        "SELECT * FROM chats WHERE status = 'active' AND (user_a = ? OR user_b = ?)",
        (tg_id, tg_id),
    )


def _peer_id(chat: dict, tg_id: int) -> int:
    return chat["user_b"] if chat["user_a"] == tg_id else chat["user_a"]


def _peer_info(peer_tg_id: int) -> dict:
    peer = _get_user(peer_tg_id)
    if not peer:
        return {"anon_num": None, "avatar": None}
    return {"anon_num": peer["anon_num"], "avatar": peer.get("avatar")}


def _auth() -> int | None:
    """Авторизация по initData из заголовка или тела запроса."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        init_data = (request.get_json(silent=True) or {}).get("init_data", "")
    if DEV_FAKE and init_data.startswith("dev:"):
        try:
            return int(init_data[4:])
        except ValueError:
            return None
    user = validate_init_data(init_data, BOT_TOKEN)
    if not user:
        return None
    return int(user["id"])


def _require() -> tuple[int, dict] | tuple[None, None]:
    tg_id = _auth()
    if tg_id is None:
        return None, None
    user = _get_user(tg_id)
    if user is None:
        return None, None
    return tg_id, user


def _err(message: str, code: int = 400):
    return jsonify({"error": message}), code


# --------------------------------------------------------------------------
# авторизация / профиль
# --------------------------------------------------------------------------

@api.post("/auth")
def auth():
    init_data = (request.get_json(silent=True) or {}).get("init_data", "")
    if DEV_FAKE and init_data.startswith("dev:"):
        tg_id = int(init_data[4:])
        tg_user = {"id": tg_id, "first_name": "Dev"}
    else:
        tg_user = validate_init_data(init_data, BOT_TOKEN)
    if not tg_user:
        return _err("Неверные данные входа", 401)

    tg_id = int(tg_user["id"])
    name = (tg_user.get("first_name") or "")[:100]

    user = _get_user(tg_id)
    if user is None:
        cur = DB.execute(
            "INSERT INTO users (tg_id, display_name, created_at) VALUES (?, ?, ?)",
            (tg_id, name, now()),
        )
        anon_num = cur.lastrowid
        DB.execute(
            "UPDATE users SET anon_num = ? WHERE tg_id = ?",
            (anon_num, tg_id),
        )
        user = _get_user(tg_id)
        notify.push(tg_id, "👋 Добро пожаловать в «Между людьми»!\n\n"
                           "Нажми «Найти собеседника» — и начинай выговариваться.")
    return jsonify(_public_user(user))


@api.get("/me")
def me():
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)
    return jsonify(_public_user(user))


@api.post("/profile")
def update_profile():
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)

    data = request.get_json(silent=True) or {}
    avatar = data.get("avatar")

    if avatar is not None:
        if not isinstance(avatar, str) or not avatar.startswith("data:image/"):
            return _err("Неверный формат аватарки")
        if len(avatar) > MAX_AVATAR:
            return _err("Аватарка слишком большая (макс. 200 КБ)")

    fields, values = [], []
    if avatar is not None:
        fields.append("avatar = ?")
        values.append(avatar)
    if "notify" in data:
        fields.append("notify = ?")
        values.append(1 if data["notify"] else 0)
    if not fields:
        return _err("Нечего менять")
    values.append(tg_id)
    DB.execute(f"UPDATE users SET {', '.join(fields)} WHERE tg_id = ?", values)
    return jsonify(_public_user(_get_user(tg_id)))


# --------------------------------------------------------------------------
# очередь и поиск собеседника
# --------------------------------------------------------------------------

@api.post("/queue")
def join_queue():
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)
    if user["banned"]:
        return _err("Аккаунт заблокирован", 403)

    with _match_lock:
        chat = _active_chat(tg_id)
        if chat:
            peer = _peer_id(chat, tg_id)
            return jsonify({"status": "chat", "chat_id": chat["id"],
                            "peer": _peer_info(peer)})

        # ищем кого-то из очереди (исключая заблокированных в обе стороны)
        waiting = DB.one(
            "SELECT tq.tg_id FROM queue tq "
            "JOIN users u ON u.tg_id = tq.tg_id "
            "LEFT JOIN blocks b1 ON b1.blocker_id = ? AND b1.blocked_id = tq.tg_id "
            "LEFT JOIN blocks b2 ON b2.blocker_id = tq.tg_id AND b2.blocked_id = ? "
            "WHERE tq.tg_id != ? AND u.banned = 0 "
            "  AND b1.blocked_id IS NULL AND b2.blocked_id IS NULL "
            "ORDER BY tq.joined_at LIMIT 1",
            (tg_id, tg_id, tg_id),
        )
        if waiting:
            peer_id = waiting["tg_id"]
            DB.execute("DELETE FROM queue WHERE tg_id IN (?, ?)", (tg_id, peer_id))
            cur = DB.execute(
                "INSERT INTO chats (user_a, user_b, created_at) VALUES (?, ?, ?)",
                (tg_id, peer_id, now()),
            )
            chat_id = cur.lastrowid
            msg = "🔎 Собеседник найден! Можно начинать разговор."
            notify.push(tg_id, msg)
            notify.push(peer_id, msg)
            return jsonify({"status": "chat", "chat_id": chat_id,
                            "peer": _peer_info(peer_id)})

        DB.execute("DELETE FROM queue WHERE tg_id = ?", (tg_id,))
        DB.execute(
            "INSERT INTO queue (tg_id, joined_at) VALUES (?, ?)",
            (tg_id, now()),
        )
        return jsonify({"status": "queued"})


@api.post("/leave")
def leave():
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)

    with _match_lock:
        chat = _active_chat(tg_id)
        if not chat:
            return jsonify({"status": "idle"})
        peer_id = _peer_id(chat, tg_id)
        close_chat(chat["id"])
        notify.push(peer_id, "👤 Собеседник покинул чат.")
        return jsonify({"status": "idle"})


@api.post("/cancel")
def cancel_queue():
    """Отменить поиск (если ещё не найден)."""
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)
    DB.execute("DELETE FROM queue WHERE tg_id = ?", (tg_id,))
    return jsonify({"status": "idle"})


# --------------------------------------------------------------------------
# сообщения + long-polling
# --------------------------------------------------------------------------

@api.get("/poll")
def poll():
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)

    if user["banned"]:
        return jsonify({"status": "banned", "reason": user.get("banned_reason")})

    try:
        since_msg = int(request.args.get("since_msg", 0))
        since_note = int(request.args.get("since_note", 0))
        timeout = min(int(request.args.get("timeout", 25)), 40)
    except ValueError:
        return _err("Неверные параметры")

    deadline = time.time() + max(timeout, 0)
    while True:
        payload = _poll_state(tg_id, since_msg, since_note)
        busy = payload["status"] in ("chat", "queued") or payload.get("events")
        if busy or time.time() >= deadline:
            return jsonify(payload)
        time.sleep(1.0)


def _poll_state(tg_id: int, since_msg: int, since_note: int) -> dict:
    user = _get_user(tg_id)
    if user is None:
        return {"status": "unauthorized"}
    if user["banned"]:
        return {"status": "banned", "reason": user.get("banned_reason")}

    notify.touch(tg_id)

    events = []

    chat = _active_chat(tg_id)
    queued = DB.one("SELECT tg_id FROM queue WHERE tg_id = ?", (tg_id,))

    if chat:
        peer = _peer_info(_peer_id(chat, tg_id))
        messages = DB.all(
            "SELECT id, sender_id, text, type, voice_dur, created_at FROM messages "
            "WHERE chat_id = ? AND id > ? ORDER BY id",
            (chat["id"], since_msg),
        )
        status = "chat"
        peer_tg = _peer_id(chat, tg_id)
        last_type = _typing_times.get((chat["id"], peer_tg), 0)
        peer_typing = (time.time() - last_type) < TYPING_TTL
    else:
        peer = None
        messages = []
        peer_typing = False
        if queued:
            status = "queued"
        else:
            status = "idle"

    notes = DB.all(
        "SELECT id, text, created_at FROM notifications "
        "WHERE tg_id = ? AND id > ? ORDER BY id",
        (tg_id, since_note),
    )

    return {
        "status": status,
        "chat_id": chat["id"] if chat else None,
        "peer": peer,
        "peer_typing": peer_typing,
        "messages": messages,
        "notifications": [{"id": n["id"], "text": n["text"]} for n in notes],
        "events": events,
    }


@api.post("/typing")
def typing():
    """Клиент сообщает, что пользователь набирает текст."""
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)
    chat = _active_chat(tg_id)
    if not chat:
        return jsonify({"ok": True})
    _typing_times[(chat["id"], tg_id)] = time.time()
    # подчистить старое
    now_ts = time.time()
    for key in list(_typing_times):
        if now_ts - _typing_times[key] > TYPING_TTL * 10:
            _typing_times.pop(key, None)
    return jsonify({"ok": True})


@api.post("/block")
def block():
    """Заблокировать собеседника: закрыть чат и не матчить больше никогда."""
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)

    data = request.get_json(silent=True) or {}
    target = data.get("tg_id")

    chat = _active_chat(tg_id)
    if chat and not target:
        target = _peer_id(chat, tg_id)
    if not target:
        return _err("Некого блокировать", 409)
    target = int(target)
    if target == tg_id:
        return _err("Нельзя заблокировать себя")

    try:
        DB.execute(
            "INSERT INTO blocks (blocker_id, blocked_id, created_at) VALUES (?, ?, ?)",
            (tg_id, target, now()),
        )
    except Exception:
        pass  # уже заблокирован

    if chat:
        close_chat(chat["id"])
        notify.push(target, "🚫 Тебя заблокировал собеседник.")
    return jsonify({"ok": True})


@api.post("/message")
def send_message():
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)
    if user["banned"]:
        return _err("Аккаунт заблокирован", 403)

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return _err("Пустое сообщение")
    if len(text) > MAX_TEXT:
        return _err(f"Сообщение длиннее {MAX_TEXT} символов")

    chat = _active_chat(tg_id)
    if not chat:
        return _err("Нет активного чата", 409)

    cur = DB.execute(
        "INSERT INTO messages (chat_id, sender_id, text, created_at) VALUES (?, ?, ?, ?)",
        (chat["id"], tg_id, text, now()),
    )
    peer_id = _peer_id(chat, tg_id)
    notify.push(peer_id, f"💬 Новое сообщение: {text[:100]}", force=False)
    return jsonify({"id": cur.lastrowid, "chat_id": chat["id"]})


MAX_VOICE = 700_000   # ~500KB base64 (примерно 60 секунд opus)
MAX_VOICE_DUR = 65


@api.post("/voice")
def send_voice():
    """Голосовое сообщение: dataURL аудио (base64) в БД."""
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)
    if user["banned"]:
        return _err("Аккаунт заблокирован", 403)

    data = request.get_json(silent=True) or {}
    audio = data.get("audio") or ""
    try:
        dur = float(data.get("dur") or 0)
    except (TypeError, ValueError):
        return _err("Неверная длительность")

    if not audio.startswith("data:audio/") or ";base64," not in audio:
        return _err("Неверный формат аудио")
    if len(audio) > MAX_VOICE:
        return _err("Запись слишком длинная (максимум 60 секунд)")
    if not (0.5 <= dur <= MAX_VOICE_DUR):
        return _err("Длительность записи: от 1 до 60 секунд")

    chat = _active_chat(tg_id)
    if not chat:
        return _err("Нет активного чата", 409)

    cur = DB.execute(
        "INSERT INTO messages (chat_id, sender_id, text, type, voice_data, voice_dur, created_at) "
        "VALUES (?, ?, '', 'voice', ?, ?, ?)",
        (chat["id"], tg_id, audio, dur, now()),
    )
    peer_id = _peer_id(chat, tg_id)
    notify.push(peer_id, "🎤 Голосовое сообщение", force=False)
    return jsonify({"id": cur.lastrowid, "chat_id": chat["id"]})


def _check_voice_access(msg_id: int) -> int | None:
    """Проверяет, что tg_id имеет доступ к голосовому. Возвращает tg_id или None."""
    init_data = request.args.get("init_data") or request.headers.get(
        "X-Telegram-Init-Data", "")
    if DEV_FAKE and init_data.startswith("dev:"):
        try:
            tg_id = int(init_data[4:])
        except ValueError:
            return None
    else:
        u = validate_init_data(init_data, BOT_TOKEN)
        if not u:
            return None
        tg_id = int(u["id"])

    m = DB.one("SELECT chat_id FROM messages WHERE id = ? AND type = 'voice'",
               (int(msg_id),))
    if not m:
        return None
    chat = DB.one("SELECT user_a, user_b FROM chats WHERE id = ?", (m["chat_id"],))
    if not chat or tg_id not in (chat["user_a"], chat["user_b"]):
        return None
    return tg_id


@api.get("/voice/<int:msg_id>")
def get_voice(msg_id):
    """Отдаёт аудио участнику чата (для <audio src>)."""
    if _check_voice_access(msg_id) is None:
        return _err("Нет доступа", 403)
    m = DB.one(
        "SELECT voice_data FROM messages WHERE id = ? AND type = 'voice'",
        (int(msg_id),),
    )
    if not m or not m.get("voice_data"):
        return _err("Не найдено", 404)
    header, b64 = m["voice_data"].split(";base64,", 1)
    mime = header.replace("data:", "") or "audio/webm"
    return Response(base64.b64decode(b64), mimetype=mime)


# --------------------------------------------------------------------------
# жалобы
# --------------------------------------------------------------------------

@api.post("/report")
def report():
    tg_id, user = _require()
    if user is None:
        return _err("Не авторизован", 401)

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()[:500]
    evidence = (data.get("evidence") or "").strip()[:4000]
    chat_id = data.get("chat_id")

    if not reason:
        return _err("Укажи причину жалобы")

    chat = None
    if chat_id:
        chat = DB.one("SELECT * FROM chats WHERE id = ?", (int(chat_id),))
    if not chat:
        chat = _active_chat(tg_id)
    if not chat:
        return _err("Нет чата, на который можно пожаловаться", 409)

    accused = _peer_id(chat, tg_id)
    report_id = create_report(tg_id, accused, chat["id"], reason, evidence)
    DB.execute("UPDATE messages SET reported = 1 WHERE chat_id = ?", (chat["id"],))
    return jsonify({"ok": True, "report_id": report_id})


# --------------------------------------------------------------------------
# админка
# --------------------------------------------------------------------------

def _admin_required():
    tg_id, user = _require()
    if user is None:
        return None, _err("Не авторизован", 401)
    if not _is_admin(tg_id):
        return None, _err("Нет прав администратора", 403)
    return tg_id, None


@api.get("/admin/reports")
def admin_reports():
    _, err = _admin_required()
    if err:
        return err
    status = request.args.get("status", "new")
    return jsonify(list_reports(status))


@api.post("/admin/reports/<int:report_id>/resolve")
def admin_resolve(report_id):
    _, err = _admin_required()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    resolve_report(report_id, data.get("status", "done"))
    return jsonify({"ok": True})


@api.post("/admin/users/<int:target_id>/ban")
def admin_ban(target_id):
    _, err = _admin_required()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "нарушение правил")[:500]

    chats = close_active_chats(target_id)
    ban_user(target_id, reason)

    notify.push(target_id, f"⛔ Ты заблокирован модератором.\nПричина: {reason}")
    for chat in chats:
        peer = chat["user_b"] if chat["user_a"] == target_id else chat["user_a"]
        notify.push(peer, "🚫 Собеседник заблокирован модератором.")
    return jsonify({"ok": True})


@api.post("/admin/users/<int:target_id>/unban")
def admin_unban(target_id):
    _, err = _admin_required()
    if err:
        return err
    unban_user(target_id)
    notify.push(target_id, "✅ Ты снова можешь пользоваться приложением.")
    return jsonify({"ok": True})


@api.get("/admin/banned")
def admin_banned():
    _, err = _admin_required()
    if err:
        return err
    rows = DB.all(
        "SELECT tg_id, anon_num, banned_reason FROM users "
        "WHERE banned = 1 ORDER BY tg_id"
    )
    return jsonify(rows)


@api.get("/admin/stats")
def admin_stats():
    _, err = _admin_required()
    if err:
        return err
    stats = {
        "users": DB.one("SELECT COUNT(*) AS c FROM users")["c"],
        "banned": DB.one("SELECT COUNT(*) AS c FROM users WHERE banned = 1")["c"],
        "chats": DB.one("SELECT COUNT(*) AS c FROM chats")["c"],
        "messages": DB.one("SELECT COUNT(*) AS c FROM messages")["c"],
        "new_reports": DB.one(
            "SELECT COUNT(*) AS c FROM reports WHERE status = 'new'"
        )["c"],
    }
    return jsonify(stats)
