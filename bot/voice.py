"""Voice message processing: Whisper STT + GPT structured extraction."""

import io
import json
import logging
from datetime import date

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_api_key = None
_client = None


def init(api_key: str) -> None:
    """Initialize OpenAI client with the given API key."""
    global _api_key, _client
    _api_key = api_key
    _client = AsyncOpenAI(api_key=api_key) if api_key else None


EVENT_SYSTEM_PROMPT = f"""\
Ты — помощник для запоминания важных дат. Из текста пользователя извлеки:
- type: один из birthday, anniversary, other
- name: имя человека или название события
- day: число месяца (1-31)
- month: число месяца (1-12)

Сегодня {date.today().isoformat()}.
Если пользователь упоминает несколько дат — верни массив объектов.
Если одну — верни один объект (НЕ массив).

Ответь ТОЛЬКО валидным JSON без markdown-обёртки."""


async def transcribe(voice_bytes: bytes, filename: str = "voice.ogg") -> str | None:
    """Transcribe audio bytes via Whisper API. Returns text or None."""
    if not _client:
        return None
    buf = io.BytesIO(voice_bytes)
    buf.name = filename
    resp = await _client.audio.transcriptions.create(
        model="whisper-1",
        file=buf,
        language="ru",
    )
    text = resp.text.strip()
    logger.info("Whisper transcription: %s", text)
    return text


async def parse_event(text: str) -> dict | list[dict] | None:
    """Extract event data from natural language text. Returns dict, list, or None."""
    if not _client:
        return None
    resp = await _client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": EVENT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
    )
    raw = resp.choices[0].message.content.strip()
    logger.info("GPT parse_event raw: %s", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse GPT response as JSON")
        return None
    if isinstance(data, dict) and "type" in data and "name" in data:
        return data
    if isinstance(data, list) and all(isinstance(d, dict) for d in data):
        return data
    return None
