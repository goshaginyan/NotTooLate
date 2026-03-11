# NotTooLate — Claude Rules

## Проект

Telegram-бот + PWA для напоминаний о важных датах (дни рождения, годовщины).

## Архитектура

- `bot/main.py` — Telegram-бот, python-telegram-bot v21+ (polling), точка входа
- `bot/web.py` — aiohttp HTTP API, работает в одном event loop с ботом
- `bot/storage.py` — хранилище, JSON-файлы в `bot/data/{user_id}.json`, async-safe с per-user locks
- `bot/voice.py` — голосовой ввод через OpenAI Whisper + GPT-4o-mini
- `bot/datepicker.py` — inline-календарь для Telegram
- `bot/miniapp/index.html` — Telegram Mini App
- `static-site/` — standalone PWA (vanilla JS, service worker, offline)

## Соглашения

- Язык интерфейса бота: русский
- Web-приложение: двуязычное (русский/английский)
- Хранилище: JSON-файлы, без БД — не усложнять
- Бот-хендлеры: ConversationHandler с состояниями, reply keyboard для навигации
- API: REST, авторизация через Telegram initData (HMAC-SHA256)
- Типы событий: `birthday`, `anniversary`, `other`

## Запуск и деплой

```bash
cd bot && python3 main.py
```

- Деплой: Railway, автодеплой из `main`
- Env: `BOT_TOKEN` (обязательно), `OPENAI_API_KEY` (для голоса), `WEB_PORT` (default 8080)

## Линтеры

- Python: `ruff check` (если установлен) или стандартный flake8
- Bash: `shellcheck`
- Dockerfile: `hadolint`

## Стиль кода

- Python: async/await, type hints где уместно
- Не добавлять лишние абстракции — проект простой, держать его таким
- Коммиты: conventional commits (fix:, feat:, chore:, etc.)
