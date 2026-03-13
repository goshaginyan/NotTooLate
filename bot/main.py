"""
NotTooLate Telegram Bot — manage important dates via Telegram.

Features:
  • Add / view / edit / delete dates
  • Persistent reply keyboard for main actions
  • Inline keyboards for selection within flows

Requires BOT_TOKEN env var (or .env file next to this script).
"""

import asyncio
import os
import datetime
import logging
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    MenuButtonCommands,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

from datepicker import DatePicker
import storage
import voice
from web import create_app

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────
TYPE_EMOJI = {"birthday": "🎂", "anniversary": "💍", "other": "⭐"}
TYPE_LABEL = {"birthday": "День рождения", "anniversary": "Годовщина", "other": "Другое"}
NAME_PRESETS = {
    "birthday": [
        ("👩", "Мама"), ("👨", "Папа"), ("👫", "Брат"), ("👭", "Сестра"),
        ("💑", "Жена"), ("💑", "Муж"), ("👵", "Бабушка"), ("👴", "Дедушка"),
        ("👶", "Ребёнок"), ("🧑\u200d🤝\u200d🧑", "Друг"),
    ],
    "anniversary": [
        ("💒", "Свадьба"), ("💑", "Годовщина знакомства"), ("🏠", "Новоселье"),
    ],
    "other": [
        ("📅", "Памятная дата"), ("🎓", "Выпускной"), ("🏆", "Достижение"),
    ],
}
MONTHS = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
# ── Button labels (used for ReplyKeyboard and matching) ──────────────
BTN_ADD = "➕ Добавить дату"
BTN_LIST = "📋 Все даты"
BTN_EDIT = "✏️ Редактировать"
BTN_HELP = "❓ Помощь"
BTN_DELETE = "🗑 Удалить"
BTN_CANCEL = "❌ Отмена"

# ── Conversation states ──────────────────────────────────────────────
(ADD_NAME, ADD_DATE, ADD_TYPE,
 EDIT_PICK, EDIT_FIELD, EDIT_NAME, EDIT_DATE, EDIT_TYPE,
 DELETE_CONFIRM) = range(9)


# ── Keyboards ────────────────────────────────────────────────────────

def main_keyboard() -> ReplyKeyboardMarkup:
    """Persistent main menu keyboard at the bottom of the chat."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_ADD)],
            [KeyboardButton(BTN_LIST), KeyboardButton(BTN_EDIT)],
            [KeyboardButton(BTN_DELETE), KeyboardButton(BTN_HELP)],
        ],
        resize_keyboard=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown during conversation with only Cancel button."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(BTN_CANCEL)]],
        resize_keyboard=True,
    )


# ── Helpers ──────────────────────────────────────────────────────────

def _html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _days_until(day: int, month: int) -> int:
    today = datetime.date.today()
    target = datetime.date(today.year, month, day)
    if target < today:
        target = datetime.date(today.year + 1, month, day)
    return (target - today).days


def _format_event(e: dict) -> str:
    emoji = TYPE_EMOJI.get(e["type"], "⭐")
    label = TYPE_LABEL.get(e["type"], e["type"])
    days = _days_until(e["day"], e["month"])
    day_str = f'{e["day"]:02d}.{e["month"]:02d}'
    if days == 0:
        when = "сегодня! 🎉"
    elif days == 1:
        when = "завтра"
    else:
        when = f"через {days} дн."
    return f"{emoji} <b>{_html(e['name'])}</b>  <i>{_html(label)}</i>\n  📅 {day_str} ({when})"



def _type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎂 День рождения", callback_data="type_birthday")],
        [InlineKeyboardButton("💍 Годовщина", callback_data="type_anniversary")],
        [InlineKeyboardButton("⭐ Другое", callback_data="type_other")],
    ])


_MAX_ROW_LEN = 25  # max total chars in a row of buttons before wrapping


def _presets_keyboard(event_type: str) -> InlineKeyboardMarkup:
    presets = NAME_PRESETS.get(event_type, [])
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    current_len = 0
    for emoji, label in presets:
        text = f"{emoji} {label}"
        btn = InlineKeyboardButton(text, callback_data=f"preset_{label}")
        if current_row and current_len + len(text) > _MAX_ROW_LEN:
            rows.append(current_row)
            current_row = [btn]
            current_len = len(text)
        else:
            current_row.append(btn)
            current_len += len(text)
    if current_row:
        rows.append(current_row)
    return InlineKeyboardMarkup(rows)


# ── Date pickers ─────────────────────────────────────────────────────
add_picker = DatePicker(prefix="adate", show_year=False)
edit_picker = DatePicker(prefix="edate", show_year=False)


# ── Command Handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {_html(user.first_name)}!\n\n"
        "<b>NotTooLate</b> — бот для важных дат.\n\n"
        "Используй кнопки внизу или команды:\n"
        f"  {BTN_ADD} — добавить дату\n"
        f"  {BTN_LIST} — посмотреть все даты\n"
        f"  {BTN_EDIT} — редактировать дату\n"
        f"  {BTN_DELETE} — удалить дату\n"
        f"  {BTN_HELP} — справка",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 <b>Как пользоваться NotTooLate</b>\n\n"
        f"<b>{BTN_ADD}</b> или /add — добавить дату\n"
        f"<b>{BTN_LIST}</b> или /list — показать все даты\n"
        f"<b>{BTN_EDIT}</b> или /edit — редактировать\n"
        f"<b>{BTN_DELETE}</b> или /delete — удалить\n\n"
        "При добавлении даты:\n"
        "1. Выберите тип события\n"
        "2. Введите имя человека\n"
        "3. Выберите дату в календаре\n\n"
        f"Нажмите <b>{BTN_CANCEL}</b> чтобы отменить.",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    events = storage.get_events(user_id)
    if not events:
        await update.message.reply_text(
            "📭 У вас пока нет дат.\n\n"
            f"Нажмите <b>{BTN_ADD}</b> чтобы добавить первую!",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    events.sort(key=lambda e: _days_until(e["day"], e["month"]))
    for e in events:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit:{e['id']}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{e['id']}"),
        ]])
        await update.message.reply_text(
            _format_event(e), parse_mode="HTML", reply_markup=kb,
        )


async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    events = storage.get_events(user_id)
    if not events:
        await update.message.reply_text(
            "📭 Нет дат для редактирования.",
            reply_markup=main_keyboard(),
        )
        return

    await update.message.reply_text("✏️ Редактирование", reply_markup=cancel_keyboard())
    events.sort(key=lambda e: _days_until(e["day"], e["month"]))
    keyboard = []
    for e in events:
        emoji = TYPE_EMOJI.get(e["type"], "⭐")
        label = f'{emoji} {e["name"]} — {e["day"]:02d}.{e["month"]:02d}'
        keyboard.append([InlineKeyboardButton(label, callback_data=f"edit:{e['id']}")])

    await update.message.reply_text(
        "Выберите дату:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of events with inline buttons to pick which to delete."""
    user_id = update.effective_user.id
    events = storage.get_events(user_id)
    if not events:
        await update.message.reply_text(
            "📭 Нет дат для удаления.",
            reply_markup=main_keyboard(),
        )
        return

    await update.message.reply_text("🗑 Удаление", reply_markup=cancel_keyboard())
    events.sort(key=lambda e: _days_until(e["day"], e["month"]))
    keyboard = []
    for e in events:
        emoji = TYPE_EMOJI.get(e["type"], "⭐")
        label = f'{emoji} {e["name"]} — {e["day"]:02d}.{e["month"]:02d}'
        keyboard.append([InlineKeyboardButton(label, callback_data=f"del:{e['id']}")])
    await update.message.reply_text(
        "Выберите дату:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Delete callback (from list or edit) ──────────────────────────────

async def delete_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split(":")[1])
    user_id = update.effective_user.id

    event = storage.get_event(user_id, event_id)
    if not event:
        await query.edit_message_text("⚠️ Дата не найдена.")
        return

    ctx.user_data["del_id"] = event_id
    await query.edit_message_text(
        f"🗑 Удалить <b>{_html(event['name'])}</b>?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data="delconfirm:yes"),
             InlineKeyboardButton("❌ Нет", callback_data="delconfirm:no")],
        ]),
    )


async def delete_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":")[1]

    if choice == "yes":
        event_id = ctx.user_data.pop("del_id", None)
        if event_id and storage.delete_event(query.from_user.id, event_id):
            await query.edit_message_text("🗑 Удалено.")
        else:
            await query.edit_message_text("⚠️ Дата не найдена.")
    else:
        ctx.user_data.pop("del_id", None)
        await query.edit_message_text("↩️ Отменено.")


# ── Edit callback (from list or edit command) ────────────────────────

async def edit_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    event_id = int(query.data.split(":")[1])
    user_id = update.effective_user.id

    event = storage.get_event(user_id, event_id)
    if not event:
        await query.edit_message_text("⚠️ Дата не найдена.")
        return

    ctx.user_data["edit_id"] = event_id
    await query.edit_message_text(
        f"{_format_event(event)}\n\nЧто изменить?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Имя", callback_data="ef:name"),
             InlineKeyboardButton("📅 Дата", callback_data="ef:date")],
        ]),
    )


async def edit_field_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[1]
    event_id = ctx.user_data.get("edit_id")

    if field == "name":
        await query.edit_message_text("📝 Введите новое <b>имя</b>:", parse_mode="HTML")
        return  # handled by edit_name_conv

    if field == "date":
        today = datetime.date.today()
        kb = edit_picker.build(today.year, today.month)
        await query.edit_message_text("📅 Выберите новую дату:", reply_markup=kb)
        return  # handled by edit_date_conv_cb



# ── Add conversation ─────────────────────────────────────────────────

async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["new_event"] = {}
    await update.message.reply_text("➕ Добавление даты", reply_markup=cancel_keyboard())
    await update.message.reply_text(
        "🏷 Выберите <b>тип</b> события:",
        parse_mode="HTML",
        reply_markup=_type_keyboard(),
    )
    return ADD_TYPE


async def add_type_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    event_type = query.data.split("_", 1)[1]
    ctx.user_data["new_event"]["type"] = event_type
    await query.edit_message_text(
        f"🏷 Тип: {TYPE_EMOJI.get(event_type, '')} {TYPE_LABEL.get(event_type, event_type)}"
    )
    await query.message.reply_text(
        "✏️ Выберите или введите <b>имя</b>:",
        parse_mode="HTML",
        reply_markup=_presets_keyboard(event_type),
    )
    return ADD_NAME


async def add_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["new_event"]["name"] = update.message.text.strip()
    today = datetime.date.today()
    kb = add_picker.build(today.year, today.month)
    await update.message.reply_text("📅 Выберите дату:", reply_markup=kb)
    return ADD_DATE


async def add_name_preset_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    name = query.data.split("_", 1)[1]
    ctx.user_data["new_event"]["name"] = name
    await query.edit_message_text(f"✏️ Имя: {name}")
    today = datetime.date.today()
    kb = add_picker.build(today.year, today.month)
    await query.message.reply_text("📅 Выберите дату:", reply_markup=kb)
    return ADD_DATE


async def add_date_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle calendar navigation and day selection for add flow."""
    query = update.callback_query
    await query.answer()
    result = add_picker.parse(query.data)

    if result[0] == "noop":
        return ADD_DATE

    if result[0] == "navigate":
        _, year, month = result
        kb = add_picker.build(year, month)
        await query.edit_message_reply_markup(reply_markup=kb)
        return ADD_DATE

    if result[0] == "day":
        _, year, month, day = result
        nd = ctx.user_data["new_event"]
        event = storage.add_event(
            query.from_user.id, nd["name"], day, month, nd["type"],
        )
        d = datetime.date(year, month, day)
        await query.edit_message_text(f"📅 Дата: {d.strftime('%d.%m')}")
        await query.message.reply_text(
            f"✅ Дата добавлена!\n\n{_format_event(event)}",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        ctx.user_data.pop("new_event", None)
        return ConversationHandler.END

    return ADD_DATE


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.pop("new_event", None)
    await update.message.reply_text(
        "❌ Добавление отменено.",
        reply_markup=main_keyboard(),
    )
    return ConversationHandler.END


# ── Edit conversation ────────────────────────────────────────────────

async def edit_conv_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry into edit conversation from inline button (ef:name, ef:day, etc.)."""
    query = update.callback_query
    await query.answer()
    field = query.data.split(":")[1]

    if field == "name":
        await query.edit_message_text("📝 Введите новое <b>имя</b>:", parse_mode="HTML")
        return EDIT_NAME

    if field == "date":
        today = datetime.date.today()
        kb = edit_picker.build(today.year, today.month)
        await query.edit_message_text("📅 Выберите новую дату:", reply_markup=kb)
        return EDIT_DATE

    return ConversationHandler.END


async def edit_name_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    event = storage.update_event(
        update.effective_user.id, ctx.user_data["edit_id"], name=new_name,
    )
    await update.message.reply_text(
        f"✅ Обновлено!\n\n{_format_event(event)}",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )
    return ConversationHandler.END


async def edit_date_conv_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle calendar navigation and day selection for edit flow."""
    query = update.callback_query
    await query.answer()
    result = edit_picker.parse(query.data)

    if result[0] == "noop":
        return EDIT_DATE

    if result[0] == "navigate":
        _, year, month = result
        kb = edit_picker.build(year, month)
        await query.edit_message_reply_markup(reply_markup=kb)
        return EDIT_DATE

    if result[0] == "day":
        _, year, month, day = result
        event = storage.update_event(
            query.from_user.id, ctx.user_data["edit_id"], day=day, month=month,
        )
        d = datetime.date(year, month, day)
        await query.edit_message_text(f"📅 Дата: {d.strftime('%d.%m')}")
        await query.message.reply_text(
            f"✅ Обновлено!\n\n{_format_event(event)}",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return ConversationHandler.END

    return EDIT_DATE


async def edit_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.pop("edit_id", None)
    await update.message.reply_text(
        "❌ Редактирование отменено.",
        reply_markup=main_keyboard(),
    )
    return ConversationHandler.END


# ── Conversation fallbacks ───────────────────────────────────────────

async def fallback_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await cmd_start(update, ctx)
    return ConversationHandler.END


async def fallback_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await cmd_list(update, ctx)
    return ConversationHandler.END


async def fallback_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await cmd_edit(update, ctx)
    return ConversationHandler.END


async def fallback_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await cmd_delete(update, ctx)
    return ConversationHandler.END


async def fallback_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await cmd_help(update, ctx)
    return ConversationHandler.END


# ── Payments (Telegram Stars) ─────────────────────────────────────────


async def cmd_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show premium status or send invoice."""
    uid = update.message.from_user.id
    if storage.is_premium(uid):
        await update.message.reply_text(
            "⭐ У вас уже активирован безлимитный голосовой ввод!",
            reply_markup=main_keyboard(),
        )
        return
    used = storage.get_voice_count(uid)
    remaining = max(0, VOICE_FREE_LIMIT - used)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"⭐ Купить — {PREMIUM_PRICE_STARS} Stars",
            callback_data="buy_premium",
        ),
    ]])
    await update.message.reply_text(
        f"🎙 <b>Голосовой ввод</b>\n\n"
        f"Использовано: {used}/{VOICE_FREE_LIMIT} бесплатных\n"
        f"Осталось: {remaining}\n\n"
        f"Безлимитный доступ — <b>{PREMIUM_PRICE_STARS} Stars</b> (разовая покупка).",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def buy_premium_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Stars invoice when user taps buy button."""
    query = update.callback_query
    await query.answer()
    await ctx.bot.send_invoice(
        chat_id=query.message.chat_id,
        title="Безлимитный голосовой ввод",
        description="Безлимитное распознавание голосовых сообщений для добавления дат",
        payload=PREMIUM_PAYLOAD,
        currency="XTR",
        prices=[LabeledPrice("Безлимитный голосовой ввод", PREMIUM_PRICE_STARS)],
    )


async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve pre-checkout query for Stars payment."""
    query = update.pre_checkout_query
    if query.invoice_payload == PREMIUM_PAYLOAD:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Неизвестный платёж")


async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Grant premium after successful Stars payment."""
    payment = update.message.successful_payment
    if payment.invoice_payload == PREMIUM_PAYLOAD:
        uid = update.message.from_user.id
        storage.set_premium(uid)
        logger.info(
            "Premium activated for user %d (charge_id=%s)",
            uid,
            payment.telegram_payment_charge_id,
        )
        await update.message.reply_text(
            "✅ Безлимитный голосовой ввод активирован!\n\n"
            "Теперь можете отправлять голосовые сообщения без ограничений.",
            reply_markup=main_keyboard(),
        )


# ── Post-init: set commands & menu button ────────────────────────────

async def post_init(app: Application) -> None:
    commands = [
        BotCommand("add", "Добавить дату"),
        BotCommand("list", "Все даты"),
        BotCommand("edit", "Редактировать"),
        BotCommand("delete", "Удалить"),
        BotCommand("premium", "Голосовой ввод ⭐"),
        BotCommand("help", "Справка"),
    ]
    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Bot commands and menu button configured.")


# ── Daily reminders ──────────────────────────────────────────────────

async def _send_reminders(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send reminders for events happening today, tomorrow, or in 7 days."""
    data_dir = storage.DATA_DIR
    logger.info("Reminder check: data_dir=%s exists=%s", data_dir, data_dir.exists())
    if data_dir.exists():
        logger.info("Data files: %s", list(data_dir.glob("*.json")))

    user_ids = storage.get_all_user_ids()
    logger.info("Reminder check: %d users found", len(user_ids))

    for user_id in user_ids:
        events = storage.get_events(user_id)
        logger.info("User %s: %d events", user_id, len(events))
        for e in events:
            days = _days_until(e["day"], e["month"])
            logger.info("  Event %s: day=%d month=%d days_until=%d", e["name"], e["day"], e["month"], days)
            emoji = TYPE_EMOJI.get(e["type"], "⭐")
            name = _html(e["name"])
            label = _html(TYPE_LABEL.get(e["type"], e["type"])).lower()

            if days == 0:
                text = f"🎉 <b>Сегодня</b> {label} — {emoji} <b>{name}</b>!\nНе забудьте поздравить!"
            elif days == 1:
                text = f"🔔 <b>Завтра</b> {label} — {emoji} <b>{name}</b>\nНе забудьте поздравить!"
            elif days == 7:
                text = f"📅 Через неделю {label} — {emoji} <b>{name}</b>\nУспейте подготовиться!"
            else:
                continue

            try:
                await ctx.bot.send_message(user_id, text, parse_mode="HTML")
                logger.info("Reminder sent to %s: %s (in %d days)", user_id, e["name"], days)
            except Exception as exc:
                logger.warning("Failed to send reminder to %s: %s", user_id, exc)


# ── Voice message handler ─────────────────────────────────────────────

VOICE_FREE_LIMIT = 5
VOICE_MAX_DURATION = 60  # seconds
PREMIUM_PRICE_STARS = 50  # Telegram Stars
PREMIUM_PAYLOAD = "premium_voice"


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice message: transcribe via Whisper, parse event via GPT."""
    msg = update.message
    uid = msg.from_user.id

    # Check duration
    if msg.voice.duration > VOICE_MAX_DURATION:
        await msg.reply_text(
            f"⚠️ Голосовое сообщение слишком длинное (макс. {VOICE_MAX_DURATION} сек).",
            reply_markup=main_keyboard(),
        )
        return

    # Check free limit
    if not storage.is_premium(uid) and storage.get_voice_count(uid) >= VOICE_FREE_LIMIT:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"⭐ Безлимит — {PREMIUM_PRICE_STARS} Stars",
                callback_data="buy_premium",
            ),
        ]])
        await msg.reply_text(
            f"🔒 Бесплатный лимит ({VOICE_FREE_LIMIT} голосовых) исчерпан.\n\n"
            "Для безлимитного голосового ввода — оформите подписку:",
            reply_markup=kb,
        )
        return

    await msg.reply_text("🎙 Распознаю голосовое...")

    try:
        voice_file = await msg.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        text = await voice.transcribe(bytes(voice_bytes))
        if not text:
            await msg.reply_text(
                "⚠️ Не удалось распознать голосовое сообщение.",
                reply_markup=main_keyboard(),
            )
            return

        await msg.reply_text(f"📝 <i>{_html(text)}</i>", parse_mode="HTML")

        data = await voice.parse_event(text)
        if not data:
            await msg.reply_text(
                "⚠️ Не удалось извлечь данные.\nПопробуйте ещё раз, например:\n"
                "<i>«День рождения мамы пятнадцатого июня»</i>",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
            return

        items = data if isinstance(data, list) else [data]
        created = []
        for item in items:
            event = storage.add_event(
                user_id=uid,
                name=item.get("name", ""),
                day=item.get("day", 1),
                month=item.get("month", 1),
                event_type=item.get("type", "other"),
            )
            created.append(event)

        storage.increment_voice_count(uid)

        lines = [_format_event(e) for e in created]
        count = len(created)
        word = "дата" if count == 1 else "даты" if count < 5 else "дат"
        remaining = VOICE_FREE_LIMIT - storage.get_voice_count(uid)
        text_msg = f"✅ Добавлено {count} {word}!\n\n" + "\n\n".join(lines)
        if not storage.is_premium(uid) and remaining >= 0:
            text_msg += f"\n\n🎙 Осталось голосовых: {remaining}/{VOICE_FREE_LIMIT}"
        await msg.reply_text(text_msg, parse_mode="HTML", reply_markup=main_keyboard())
    except Exception as exc:
        logger.exception("Voice handler error")
        await msg.reply_text(
            f"⚠️ Ошибка: <code>{_html(str(exc))}</code>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )


# ── Standalone cancel (outside conversations) ────────────────────────

async def cancel_standalone(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Cancel button press outside of any conversation."""
    await update.message.reply_text("↩️ Отменено.", reply_markup=main_keyboard())


# ── Main ─────────────────────────────────────────────────────────────

_CANCEL_FILTERS = filters.Text([BTN_CANCEL])
_NAV_FILTERS = filters.Text([BTN_LIST, BTN_EDIT, BTN_DELETE, BTN_HELP])
_TEXT_INPUT = filters.TEXT & ~filters.COMMAND & ~_CANCEL_FILTERS & ~_NAV_FILTERS


def _build_bot_app(token: str) -> Application:
    app = Application.builder().token(token).post_init(post_init).build()

    _fallbacks = [
        CommandHandler("start", fallback_start),
        CommandHandler("help", fallback_help),
        CommandHandler("list", fallback_list),
        CommandHandler("edit", fallback_edit),
        CommandHandler("delete", fallback_delete),
        CommandHandler("cancel", add_cancel),
        MessageHandler(filters.Text([BTN_CANCEL]), add_cancel),
        MessageHandler(filters.Text([BTN_LIST]), fallback_list),
        MessageHandler(filters.Text([BTN_EDIT]), fallback_edit),
        MessageHandler(filters.Text([BTN_DELETE]), fallback_delete),
        MessageHandler(filters.Text([BTN_HELP]), fallback_help),
    ]

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_start),
            MessageHandler(filters.Text([BTN_ADD]), add_start),
        ],
        states={
            ADD_TYPE: [CallbackQueryHandler(add_type_cb, pattern=r"^type_\w+$")],
            ADD_NAME: [
                CallbackQueryHandler(add_name_preset_cb, pattern=r"^preset_"),
                MessageHandler(_TEXT_INPUT, add_name),
            ],
            ADD_DATE: [CallbackQueryHandler(add_date_cb, pattern=r"^adate:")],
        },
        fallbacks=_fallbacks,
        per_message=False,
    )

    edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_conv_start, pattern=r"^ef:"),
        ],
        states={
            EDIT_NAME: [MessageHandler(_TEXT_INPUT, edit_name_conv)],
            EDIT_DATE: [CallbackQueryHandler(edit_date_conv_cb, pattern=r"^edate:")],
        },
        fallbacks=[
            CommandHandler("start", fallback_start),
            CommandHandler("cancel", edit_cancel),
            MessageHandler(filters.Text([BTN_CANCEL]), edit_cancel),
        ],
        per_message=False,
    )

    app.add_handler(add_conv)
    app.add_handler(edit_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(MessageHandler(filters.Text([BTN_LIST]), cmd_list))
    app.add_handler(MessageHandler(filters.Text([BTN_EDIT]), cmd_edit))
    app.add_handler(MessageHandler(filters.Text([BTN_DELETE]), cmd_delete))
    app.add_handler(MessageHandler(filters.Text([BTN_HELP]), cmd_help))
    # Standalone cancel (outside conversations)
    app.add_handler(MessageHandler(filters.Text([BTN_CANCEL]), cancel_standalone))
    app.add_handler(CommandHandler("cancel", cancel_standalone))
    app.add_handler(CallbackQueryHandler(edit_callback, pattern=r"^edit:"))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern=r"^del:"))
    app.add_handler(CallbackQueryHandler(delete_confirm_callback, pattern=r"^delconfirm:"))
    app.add_handler(CallbackQueryHandler(edit_field_callback, pattern=r"^ef:"))

    # Payments (Telegram Stars)
    app.add_handler(CommandHandler("premium", cmd_premium))
    app.add_handler(CallbackQueryHandler(buy_premium_callback, pattern=r"^buy_premium$"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # Voice messages
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    return app


async def run() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set. Create bot/.env with BOT_TOKEN=<your token>")

    voice.init(os.getenv("OPENAI_API_KEY", ""))

    web_port = int(os.getenv("WEB_PORT", "8080"))

    # Build bot application
    bot_app = _build_bot_app(token)

    # Build web API
    web_app = create_app(token)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", web_port)

    # Start both
    async with bot_app:
        await bot_app.start()
        await site.start()
        logger.info("NotTooLate bot is running...")
        logger.info("Web API listening on port %d", web_port)

        await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        # TEST: send reminders 60 seconds after startup
        bot_app.job_queue.run_once(
            _send_reminders,
            when=60,
            name="test_reminders",
        )
        logger.info("TEST: reminders will fire in 60 seconds")

        # Run until interrupted
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await bot_app.updater.stop()
            await bot_app.stop()
            await runner.cleanup()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
