# NotTooLate

Приложение-напоминалка о важных датах — дни рождения, годовщины, памятные даты. Никогда не забудешь поздравить близких.

## Возможности

- Telegram-бот с диалоговым интерфейсом на русском языке
- Голосовые сообщения — скажи «День рождения мамы 15 марта» и бот всё добавит (Whisper + GPT)
- Встроенный календарь для выбора даты
- Напоминания: за 7 дней, за день и в сам день
- Web-приложение (PWA) с офлайн-режимом и двуязычным интерфейсом
- Telegram Mini App — веб-интерфейс прямо внутри Telegram

## Архитектура

```
bot/
├── main.py          # Telegram-бот (python-telegram-bot v21+)
├── web.py           # HTTP API (aiohttp), Telegram Mini App бэкенд
├── storage.py       # Хранилище — JSON-файлы по пользователям
├── voice.py         # Голосовой ввод (OpenAI Whisper + GPT-4o-mini)
├── datepicker.py    # Inline-календарь для Telegram
├── miniapp/
│   └── index.html   # Telegram Mini App
└── data/            # Данные пользователей (*.json)

static-site/
├── index.html       # PWA — standalone веб-приложение
├── manifest.json    # PWA-манифест
├── service-worker.js
├── Dockerfile       # Nginx-контейнер для static-site
└── nginx.conf
```

## Стек

- **Бот**: Python 3, python-telegram-bot 21+, aiohttp
- **AI**: OpenAI API (Whisper для транскрипции, GPT-4o-mini для парсинга)
- **Фронтенд**: Vanilla JS, CSS Variables, Service Worker, Web Notifications
- **Хранение**: JSON-файлы (без БД)
- **Деплой**: Railway (Nixpacks)

## Запуск

```bash
# Установить зависимости
pip install -r requirements.txt

# Переменные окружения
export BOT_TOKEN=your_telegram_bot_token
export OPENAI_API_KEY=your_openai_key  # опционально, для голоса
export WEB_PORT=8080                    # опционально

# Запустить бота + API
cd bot && python3 main.py
```

## Переменные окружения

| Переменная | Обязательно | Описание |
|---|---|---|
| `BOT_TOKEN` | да | Токен Telegram-бота |
| `OPENAI_API_KEY` | нет | Ключ OpenAI для голосовых сообщений |
| `WEB_PORT` | нет | Порт HTTP API (по умолчанию 8080) |

## Деплой

Хостится на Railway. Деплой автоматический из ветки `main`. Конфиг — `bot/railway.json`.
