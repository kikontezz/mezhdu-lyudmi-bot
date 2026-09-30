# Между людьми

Анонимное общение один-на-один внутри Telegram: без имён, без ников —
только аватарка, номер «Аноним #N» и собеседник.

## Что внутри

- **Mini App** (`web/`) — экраны: главное меню, поиск собеседника,
  «Собеседник найден», чат, «Чат завершён», профиль, настройки, правила,
  жалобы, админка
- **Бэкенд** (`webapp/`) — Flask API + long-polling:
  - анонимные профили (номер + аватарка, ник запрещён)
  - очередь и поиск случайного собеседника
  - чат в реальном времени, индикатор «печатает…»
  - жалобы → Discord webhook + админка (бан/разбан)
  - блокировки (пара больше никогда не встретится)
  - уведомления в Telegram (без спама: если открыт чат — не дублируем)
- **Бот** (`bot.py`) — команда `/start` с кнопкой открытия Mini App

## Локальный запуск

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# тесты (37 проверок, Telegram не нужен)
.venv/bin/python tests/smoke.py

# веб-интерфейс без Telegram (два «пользователя» для проверки чата)
.venv/bin/python tests/run_web.py
# → http://localhost:8899            (dev:111, админ)
# → http://localhost:8899/?dev=222   (dev:222)
```

## Переменные окружения

| Переменная | Зачем |
|---|---|
| `BOT_TOKEN` | токен бота от @BotFather (**обязательно**) |
| `WEB_APP_URL` | HTTPS-адрес Mini App (для кнопки в боте) |
| `ADMIN_IDS` | Telegram ID админов через запятую, напр. `1148607072` |
| `DISCORD_WEBHOOK_URL` | webhook канала, куда падают жалобы |
| `DISCORD_MENTION` | `<@id>` — кого пинговать в Discord (опционально) |
| `DATABASE_URL` | `sqlite:///data/data.db` (по умолчанию) или PostgreSQL |
| `DEV_FAKE_AUTH` | **только для разработки** — `1` включает вход `dev:<id>` |

## Деплой (Render)

1. Новый **Web Service** → подключить репозиторий
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `python bot.py`
4. Env: `BOT_TOKEN`, `WEB_APP_URL`, `ADMIN_IDS`, `DISCORD_WEBHOOK_URL`
5. `DEV_FAKE_AUTH` на проде **не задавать**
