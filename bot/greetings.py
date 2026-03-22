"""Generate personalized greetings via OpenAI API."""

import os
import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


_EVENT_TYPE_RU = {
    "birthday": "день рождения",
    "anniversary": "годовщина",
    "other": "важная дата",
}


async def generate_greeting(name: str, event_type: str) -> str:
    """Generate a unique greeting using OpenAI."""
    event_label = _EVENT_TYPE_RU.get(event_type, "важная дата")

    prompt = (
        f"Сегодня {event_label} у человека по имени/описанию: «{name}».\n"
        f"Напиши красивое, тёплое и уникальное поздравление на русском языке.\n"
        f"Учитывай, кто этот человек (мама, жена, друг, коллега и т.д.) "
        f"и подбирай соответствующий тон.\n"
        f"Поздравление должно быть 2-4 предложения, с эмодзи.\n"
        f"Отвечай только текстом поздравления, без пояснений."
    )

    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=1.0,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        logger.exception("OpenAI greeting generation failed for '%s'", name)
        return f"С праздником, {name}! Пусть этот день будет особенным! 🎉"
