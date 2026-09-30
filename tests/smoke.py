"""Smoke-тест: полный проход без реального Telegram — auth, поиск, чат, жалобы, админка."""

import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import quote, urlencode

os.environ["BOT_TOKEN"] = "123456:TEST-TOKEN"
os.environ["ADMIN_IDS"] = "999"
os.makedirs("/tmp/opencode", exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:////tmp/opencode/smoke_test.db"

if os.path.exists("/tmp/opencode/smoke_test.db"):
    os.remove("/tmp/opencode/smoke_test.db")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapp.db import init_db  # noqa: E402

init_db()

from bot import app  # noqa: E402

TOKEN = os.environ["BOT_TOKEN"]


def make_init_data(user_id: int) -> str:
    data = {
        "user": json.dumps(
            {"id": user_id, "first_name": f"User{user_id}", "username": f"u{user_id}"},
            separators=(",", ":"),
        ),
        "auth_date": str(int(time.time())),
        "query_id": "AAtest",
    }
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**data, "hash": sig})


client = app.test_client()
OK, FAIL = "✅", "❌"
fails = []


def check(name, cond, extra=""):
    print(f"{OK if cond else FAIL} {name} {extra}")
    if not cond:
        fails.append(name)


def auth(user_id):
    resp = client.post(
        "/api/auth",
        json={"init_data": make_init_data(user_id)},
    )
    return resp


def h(user_id):
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


# --- healthz + index ---
check("healthz", client.get("/healthz").status_code == 200)
check("index.html отдаётся", client.get("/").status_code == 200)

# --- auth ---
r = auth(111)
check("auth первого юзера", r.status_code == 200, str(r.get_json()))
u1 = r.get_json()
check("анонимный номер присвоен", u1.get("anon_num") is not None)

r = auth(222)
u2 = r.get_json()
check("auth второго юзера", r.status_code == 200)
check("номера разные", u1["anon_num"] != u2["anon_num"])

# --- повторный auth не создаёт дубль ---
r = auth(111)
check("повторный auth не ломает", r.get_json()["anon_num"] == u1["anon_num"])

# --- фейковая подпись отклоняется ---
bad = make_init_data(111)[:-4] + "0000"
r = client.post("/api/auth", json={"init_data": bad})
check("битая подпись = 401", r.status_code == 401)

# --- без заголовка = 401 ---
r = client.get("/api/me")
check("без initData = 401", r.status_code == 401)

# --- очередь ---
r = client.post("/api/queue", headers=h(111))
check("первый в очереди", r.get_json()["status"] == "queued", str(r.get_json()))

r = client.post("/api/queue", headers=h(222))
j = r.get_json()
check("второй получает чат", j["status"] == "chat", str(j))
chat_id = j.get("chat_id")
check("peer отдан без имени/ника", "anon_num" in (j.get("peer") or {}))

# --- сообщения ---
r = client.post("/api/message", headers=h(111), json={"text": "привет, это я"})
check("отправка сообщения", r.status_code == 200, str(r.get_json()))
msg_id = r.get_json()["id"]

r = client.post("/api/message", headers=h(222), json={"text": "и я тут"})
check("ответ", r.status_code == 200)

# --- poll видит новые сообщения ---
r = client.get(f"/api/poll?since_msg={msg_id}&since_note=0&timeout=0", headers=h(222))
p = r.get_json()
check("poll: статус chat", p["status"] == "chat")
check("poll: новое сообщение видно", len(p["messages"]) == 1, str(p["messages"]))
check("poll: уведомления приходят", len(p["notifications"]) >= 1, str(p["notifications"]))

# --- пустое и длинное сообщение ---
r = client.post("/api/message", headers=h(111), json={"text": "   "})
check("пустое сообщение отклонено", r.status_code == 400)
r = client.post("/api/message", headers=h(111), json={"text": "x" * 2000})
check("длинное сообщение отклонено", r.status_code == 400)

# --- жалоба ---
r = client.post(
    "/api/report",
    headers=h(222),
    json={"reason": "оскорбления", "evidence": "вот эти сообщения", "chat_id": chat_id},
)
check("жалоба создана", r.status_code == 200, str(r.get_json()))

# --- админка ---
auth(999)  # админ должен один раз открыть приложение
r = client.get("/api/admin/reports", headers=h(111))
check("не-админ получает 403", r.status_code == 403)
r = client.get("/api/admin/reports", headers=h(999))
check("админ видит жалобы", r.status_code == 200 and len(r.get_json()) == 1,
      str(r.get_json()))

# --- выход из чата ---
r = client.post("/api/leave", headers=h(111))
check("leave", r.status_code == 200)
r = client.get("/api/poll?timeout=0", headers=h(222))
check("peer узнал об уходе (idle)", r.get_json()["status"] == "idle")

# --- бан ---
r = client.post("/api/admin/users/222/ban", headers=h(999),
                json={"reason": "тест"})
check("бан", r.status_code == 200)
r = client.post("/api/queue", headers=h(222))
check("баненный не в очередь (403)", r.status_code == 403)
r = client.get("/api/poll?timeout=0", headers=h(222))
check("бан виден в poll", r.get_json()["status"] == "banned")

# --- разбан ---
r = client.post("/api/admin/users/222/unban", headers=h(999))
check("разбан", r.status_code == 200)
r = client.post("/api/queue", headers=h(222))
check("после разбана можно искать", r.status_code == 200)

# --- аватарка ---
r = client.post(
    "/api/profile",
    headers=h(111),
    json={"avatar": "data:image/png;base64,iVBORw0KGgo="},
)
check("аватарка сохранена", r.status_code == 200)
r = client.post("/api/profile", headers=h(111), json={"avatar": "http://evil"})
check("аватарка не-dataURL отклонена", r.status_code == 400)

# --- typing + блокировки ---
client.post("/api/cancel", headers=h(222))  # выйти из прошлой очереди
r = client.post("/api/queue", headers=h(111))
check("111 снова ищет", r.get_json()["status"] == "queued")
r = client.post("/api/queue", headers=h(222))
check("222 матчится с 111", r.get_json()["status"] == "chat", str(r.get_json()))

r = client.post("/api/typing", headers=h(222))
check("typing принят", r.status_code == 200)
r = client.get("/api/poll?timeout=0", headers=h(111))
check("peer_typing виден", r.get_json().get("peer_typing") is True, str(r.get_json().get("peer_typing")))

# 111 блокирует 222
r = client.post("/api/block", headers=h(111), json={"tg_id": 222})
check("block", r.status_code == 200, str(r.get_json()))

# теперь они не должны больше матчиться
r = client.post("/api/queue", headers=h(111))
s1 = r.get_json()["status"]
r = client.post("/api/queue", headers=h(222))
s2 = r.get_json()["status"]
check("после блока не матчатся", s1 == "queued" and s2 == "queued", f"{s1}/{s2}")

# админ видит список банов
r = client.get("/api/admin/banned", headers=h(999))
check("список банов", r.status_code == 200 and isinstance(r.get_json(), list),
      str(r.get_json()))

# --- голосовые сообщения ---
auth(333)
auth(444)
client.post("/api/cancel", headers=h(111))
client.post("/api/cancel", headers=h(222))
r = client.post("/api/queue", headers=h(333))
check("333 ищет", r.get_json()["status"] == "queued")
r = client.post("/api/queue", headers=h(444))
check("344 матчится", r.get_json()["status"] == "chat")

fake_audio = "data:audio/webm;base64," + "A" * 500
r = client.post("/api/voice", headers=h(333),
                json={"audio": fake_audio, "dur": 2.5})
check("голосовое принято", r.status_code == 200, str(r.get_json()))
vid = r.get_json()["id"]

r = client.get(f"/api/voice/{vid}?init_data={quote(make_init_data(444))}")
check("пара слышит аудио", r.status_code == 200 and r.mimetype.startswith("audio/"),
      r.mimetype)

r = client.get(f"/api/voice/{vid}?init_data={quote(make_init_data(111))}")
check("чужой не слышит (403)", r.status_code == 403)

r = client.post("/api/voice", headers=h(333),
                json={"audio": fake_audio, "dur": 100})
check("слишком длинная запись = 400", r.status_code == 400)

r = client.post("/api/voice", headers=h(333),
                json={"audio": "data:text/plain;base64,AAA", "dur": 2})
check("не-аудио = 400", r.status_code == 400)

# голосовое видно в poll как voice
r = client.get(f"/api/poll?since_msg={vid - 1}&timeout=0", headers=h(444))
p = r.get_json()
check("poll отдаёт тип voice",
      p["messages"] and p["messages"][0].get("type") == "voice",
      str(p["messages"][:1]))

print()
if fails:
    print(f"ПРОВАЛЕНО: {len(fails)} → {fails}")
    sys.exit(1)
print("ВСЕ ТЕСТЫ ПРОШЛИ")
