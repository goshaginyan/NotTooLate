"""HTTP API for NotTooLate — serves events to the Telegram Mini App.

Validates Telegram initData via HMAC-SHA256, then proxies CRUD to storage.
Runs alongside the bot in the same async loop.
"""

import hashlib
import hmac
import json
import logging
import os
from urllib.parse import parse_qs, unquote

from aiohttp import web

import storage

logger = logging.getLogger(__name__)


# ── Telegram initData validation ─────────────────────────────────────

def _validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram Web App initData and return parsed data.

    Returns the parsed data dict (including 'user') on success, None on failure.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        # Each value is a list — take the first element
        data_dict = {k: v[0] for k, v in parsed.items()}
    except Exception:
        return None

    received_hash = data_dict.pop("hash", None)
    if not received_hash:
        return None

    # Build the data-check-string: sorted key=value pairs joined by \n
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data_dict.items())
    )

    # secret_key = HMAC-SHA256(bot_token, "WebAppData")
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()

    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    # Parse the user JSON
    user_raw = data_dict.get("user")
    if user_raw:
        try:
            data_dict["user"] = json.loads(user_raw)
        except (json.JSONDecodeError, TypeError):
            return None

    return data_dict


# ── Auth middleware ───────────────────────────────────────────────────

def _make_auth_middleware(bot_token: str):
    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        # Skip CORS preflight
        if request.method == "OPTIONS":
            return await handler(request)

        # Skip non-API routes
        if not request.path.startswith("/api/"):
            return await handler(request)

        init_data = request.headers.get("X-Telegram-Init-Data", "")
        if not init_data:
            raise web.HTTPUnauthorized(text="Missing initData")

        validated = _validate_init_data(init_data, bot_token)
        if validated is None:
            raise web.HTTPUnauthorized(text="Invalid initData")

        user = validated.get("user")
        if not user or "id" not in user:
            raise web.HTTPUnauthorized(text="No user in initData")

        request["user_id"] = int(user["id"])
        return await handler(request)

    return auth_middleware


# ── CORS middleware ──────────────────────────────────────────────────

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Telegram-Init-Data",
    "Access-Control-Max-Age": "86400",
}


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=CORS_HEADERS)
    response = await handler(request)
    response.headers.update(CORS_HEADERS)
    return response


# ── Route handlers ───────────────────────────────────────────────────

async def list_events(request: web.Request) -> web.Response:
    user_id = request["user_id"]
    events = storage.get_events(user_id)
    return web.json_response(events)


async def create_event(request: web.Request) -> web.Response:
    user_id = request["user_id"]
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        raise web.HTTPBadRequest(text="Invalid JSON")

    name = body.get("name", "").strip()
    day = body.get("day")
    month = body.get("month")
    event_type = body.get("type", "other")

    if not name or not isinstance(day, int) or not isinstance(month, int):
        raise web.HTTPBadRequest(text="Missing required fields: name, day, month")

    if not (1 <= day <= 31) or not (1 <= month <= 12):
        raise web.HTTPBadRequest(text="Invalid day or month")

    if event_type not in ("birthday", "anniversary", "other"):
        raise web.HTTPBadRequest(text="Invalid type")

    event = storage.add_event(user_id, name, day, month, event_type)
    return web.json_response(event, status=201)


async def update_event(request: web.Request) -> web.Response:
    user_id = request["user_id"]
    event_id = int(request.match_info["id"])

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        raise web.HTTPBadRequest(text="Invalid JSON")

    fields = {}
    if "name" in body:
        name = body["name"].strip()
        if not name:
            raise web.HTTPBadRequest(text="Name cannot be empty")
        fields["name"] = name
    if "day" in body:
        if not isinstance(body["day"], int) or not (1 <= body["day"] <= 31):
            raise web.HTTPBadRequest(text="Invalid day")
        fields["day"] = body["day"]
    if "month" in body:
        if not isinstance(body["month"], int) or not (1 <= body["month"] <= 12):
            raise web.HTTPBadRequest(text="Invalid month")
        fields["month"] = body["month"]
    if "type" in body:
        if body["type"] not in ("birthday", "anniversary", "other"):
            raise web.HTTPBadRequest(text="Invalid type")
        fields["type"] = body["type"]

    if not fields:
        raise web.HTTPBadRequest(text="No fields to update")

    event = storage.update_event(user_id, event_id, **fields)
    if event is None:
        raise web.HTTPNotFound(text="Event not found")

    return web.json_response(event)


async def delete_event(request: web.Request) -> web.Response:
    user_id = request["user_id"]
    event_id = int(request.match_info["id"])

    if not storage.delete_event(user_id, event_id):
        raise web.HTTPNotFound(text="Event not found")

    return web.json_response({"ok": True})


# ── App factory ──────────────────────────────────────────────────────

def create_app(bot_token: str) -> web.Application:
    app = web.Application(middlewares=[
        cors_middleware,
        _make_auth_middleware(bot_token),
    ])
    app.router.add_get("/api/events", list_events)
    app.router.add_post("/api/events", create_event)
    app.router.add_put("/api/events/{id}", update_event)
    app.router.add_delete("/api/events/{id}", delete_event)
    return app
