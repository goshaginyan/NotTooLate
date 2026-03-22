"""
NotTooLate Telegram Bot — manage important dates via Telegram.

Features:
  • Add / view / edit / delete dates
  • Inline keyboard navigation
  • Callback-driven conversation (no slash-command spam)

Requires BOT_TOKEN env var (or .env file next to this script).
"""

import os
import datetime
import logging
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import storage
import greetings

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Conversation states ──────────────────────────────────────────────
(
    MAIN_MENU,
    ADD_NAME,
    ADD_DAY,
    ADD_MONTH,
    ADD_TYPE,
    EDIT_PICK,
    EDIT_FIELD,
    EDIT_NAME,
    EDIT_DAY,
    EDIT_MONTH,
    EDIT_TYPE,
    DELETE_CONFIRM,
) = range(12)

# ── Constants ────────────────────────────────────────────────────────
TYPE_EMOJI = {"birthday": "🎂", "anniversary": "💍", "other": "⭐"}
TYPE_LABEL = {"birthday": "День рождения", "anniversary": "Годовщина", "other": "Другое"}
MONTHS = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


# ── Helpers ──────────────────────────────────────────────────────────
def _days_until(day: int, month: int) -> int:
    today = datetime.date.today()
    target = datetime.date(today.year, month, day)
    if target < today:
        target = datetime.date(today.year + 1, month, day)
    return (target - today).days


def _format_event(e: dict) -> str:
    emoji = TYPE_EMOJI.get(e["type"], "⭐")
    days = _days_until(e["day"], e["month"])
    day_str = f'{e["day"]:02d}.{e["month"]:02d}'
    if days == 0:
        when = "сегодня! 🎉"
    elif days == 1:
        when = "завтра"
    else:
        when = f"через {days} дн."
    return f"{emoji} <b>{e['name']}</b> — {day_str} ({when})"


def _main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить дату", callback_data="add")],
        [InlineKeyboardButton("📋 Все даты", callback_data="list")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data="edit")],
    ])


def _month_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, 12, 3):
        rows.append([
            InlineKeyboardButton(MONTHS[j], callback_data=f"month_{j+1}")
            for j in range(i, i + 3)
        ])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def _type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎂 День рождения", callback_data="type_birthday")],
        [InlineKeyboardButton("💍 Годовщина", callback_data="type_anniversary")],
        [InlineKeyboardButton("⭐ Другое", callback_data="type_other")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ])


def _back_button(data: str = "main") -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("⬅️ Назад", callback_data=data)]


# ── /start ───────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text(
        "👋 <b>NotTooLate</b> — бот для важных дат!\n\n"
        "Выбери действие:",
        parse_mode="HTML",
        reply_markup=_main_menu_kb(),
    )
    return MAIN_MENU


# ── Main menu router ────────────────────────────────────────────────
async def main_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "add":
        await q.edit_message_text(
            "✏️ Введи <b>имя</b> человека:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([_back_button()]),
        )
        return ADD_NAME

    if data == "list":
        return await _show_list(q, ctx)

    if data == "edit":
        return await _show_edit_pick(q, ctx)

    return MAIN_MENU


# ── Add flow ─────────────────────────────────────────────────────────
async def add_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        f"📅 Введи <b>день</b> (1–31) для <i>{ctx.user_data['name']}</i>:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([_back_button()]),
    )
    return ADD_DAY


async def add_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        day = int(update.message.text)
        if not 1 <= day <= 31:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Введи число от 1 до 31.")
        return ADD_DAY
    ctx.user_data["day"] = day
    await update.message.reply_text(
        "📆 Выбери <b>месяц</b>:",
        parse_mode="HTML",
        reply_markup=_month_keyboard(),
    )
    return ADD_MONTH


async def add_month_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await _go_main(q, ctx)
    month = int(q.data.split("_")[1])
    ctx.user_data["month"] = month
    await q.edit_message_text(
        "🏷 Выбери <b>тип</b> события:",
        parse_mode="HTML",
        reply_markup=_type_keyboard(),
    )
    return ADD_TYPE


async def add_type_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await _go_main(q, ctx)
    event_type = q.data.split("_", 1)[1]
    ud = ctx.user_data
    event = storage.add_event(
        q.from_user.id, ud["name"], ud["day"], ud["month"], event_type,
    )
    await q.edit_message_text(
        f"✅ Добавлено!\n\n{_format_event(event)}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=_main_menu_kb(),
    )
    ctx.user_data.clear()
    return MAIN_MENU


# ── List ─────────────────────────────────────────────────────────────
async def _show_list(q, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    events = storage.get_events(q.from_user.id)
    if not events:
        await q.edit_message_text(
            "📭 Список пуст. Добавь первую дату!",
            reply_markup=_main_menu_kb(),
        )
        return MAIN_MENU

    events.sort(key=lambda e: _days_until(e["day"], e["month"]))
    lines = [_format_event(e) for e in events]
    text = "<b>📋 Твои даты:</b>\n\n" + "\n".join(lines)
    await q.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([_back_button()]),
    )
    return MAIN_MENU


# ── Edit / Delete flow ───────────────────────────────────────────────
async def _show_edit_pick(q, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    events = storage.get_events(q.from_user.id)
    if not events:
        await q.edit_message_text(
            "📭 Нет дат для редактирования.",
            reply_markup=_main_menu_kb(),
        )
        return MAIN_MENU

    events.sort(key=lambda e: _days_until(e["day"], e["month"]))
    buttons = []
    for e in events:
        emoji = TYPE_EMOJI.get(e["type"], "⭐")
        label = f'{emoji} {e["name"]} — {e["day"]:02d}.{e["month"]:02d}'
        buttons.append([InlineKeyboardButton(label, callback_data=f"pick_{e['id']}")])
    buttons.append(_back_button())
    await q.edit_message_text(
        "✏️ Выбери дату для редактирования:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return EDIT_PICK


async def edit_pick_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "main":
        return await _go_main(q, ctx)
    event_id = int(q.data.split("_")[1])
    event = storage.get_event(q.from_user.id, event_id)
    if not event:
        await q.edit_message_text("⚠️ Дата не найдена.", reply_markup=_main_menu_kb())
        return MAIN_MENU
    ctx.user_data["edit_id"] = event_id
    text = f"{_format_event(event)}\n\nЧто изменить?"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Имя", callback_data="ef_name"),
         InlineKeyboardButton("📅 День", callback_data="ef_day")],
        [InlineKeyboardButton("📆 Месяц", callback_data="ef_month"),
         InlineKeyboardButton("🏷 Тип", callback_data="ef_type")],
        [InlineKeyboardButton("🗑 Удалить", callback_data="ef_delete")],
        _back_button("edit"),
    ])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    return EDIT_FIELD


async def edit_field_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "edit":
        return await _show_edit_pick(q, ctx)

    if data == "ef_name":
        await q.edit_message_text(
            "📝 Введи новое <b>имя</b>:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([_back_button("edit")]),
        )
        return EDIT_NAME

    if data == "ef_day":
        await q.edit_message_text(
            "📅 Введи новый <b>день</b> (1–31):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([_back_button("edit")]),
        )
        return EDIT_DAY

    if data == "ef_month":
        await q.edit_message_text(
            "📆 Выбери новый <b>месяц</b>:",
            parse_mode="HTML",
            reply_markup=_month_keyboard(),
        )
        return EDIT_MONTH

    if data == "ef_type":
        await q.edit_message_text(
            "🏷 Выбери новый <b>тип</b>:",
            parse_mode="HTML",
            reply_markup=_type_keyboard(),
        )
        return EDIT_TYPE

    if data == "ef_delete":
        event = storage.get_event(q.from_user.id, ctx.user_data["edit_id"])
        await q.edit_message_text(
            f"🗑 Удалить <b>{event['name']}</b>?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data="del_yes"),
                 InlineKeyboardButton("❌ Нет", callback_data="del_no")],
            ]),
        )
        return DELETE_CONFIRM

    return EDIT_FIELD


async def edit_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    new_name = update.message.text.strip()
    event = storage.update_event(update.effective_user.id, ctx.user_data["edit_id"], name=new_name)
    await update.message.reply_text(
        f"✅ Обновлено!\n\n{_format_event(event)}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=_main_menu_kb(),
    )
    return MAIN_MENU


async def edit_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        day = int(update.message.text)
        if not 1 <= day <= 31:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Введи число от 1 до 31.")
        return EDIT_DAY
    event = storage.update_event(update.effective_user.id, ctx.user_data["edit_id"], day=day)
    await update.message.reply_text(
        f"✅ Обновлено!\n\n{_format_event(event)}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=_main_menu_kb(),
    )
    return MAIN_MENU


async def edit_month_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await _go_main(q, ctx)
    month = int(q.data.split("_")[1])
    event = storage.update_event(q.from_user.id, ctx.user_data["edit_id"], month=month)
    await q.edit_message_text(
        f"✅ Обновлено!\n\n{_format_event(event)}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=_main_menu_kb(),
    )
    return MAIN_MENU


async def edit_type_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        return await _go_main(q, ctx)
    event_type = q.data.split("_", 1)[1]
    event = storage.update_event(q.from_user.id, ctx.user_data["edit_id"], type=event_type)
    await q.edit_message_text(
        f"✅ Обновлено!\n\n{_format_event(event)}\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=_main_menu_kb(),
    )
    return MAIN_MENU


async def delete_confirm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    if q.data == "del_yes":
        storage.delete_event(q.from_user.id, ctx.user_data["edit_id"])
        await q.edit_message_text(
            "🗑 Удалено!\n\nВыбери действие:",
            reply_markup=_main_menu_kb(),
        )
    else:
        await q.edit_message_text(
            "↩️ Отменено.\n\nВыбери действие:",
            reply_markup=_main_menu_kb(),
        )
    return MAIN_MENU


# ── Navigation helpers ───────────────────────────────────────────────
async def _go_main(q, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await q.edit_message_text(
        "👋 <b>NotTooLate</b> — бот для важных дат!\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=_main_menu_kb(),
    )
    return MAIN_MENU


async def cancel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    return await _go_main(q, ctx)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text(
        "↩️ Отменено.\n\nВыбери действие:",
        reply_markup=_main_menu_kb(),
    )
    return MAIN_MENU


# ── Daily notification job ────────────────────────────────────────────
async def _daily_check(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Iterate all users, find today's events, send notification + greeting."""
    today = datetime.date.today()
    for user_id in storage.get_all_user_ids():
        events = storage.get_events(user_id)
        for e in events:
            if e["day"] == today.day and e["month"] == today.month:
                emoji = TYPE_EMOJI.get(e["type"], "⭐")
                type_label = TYPE_LABEL.get(e["type"], "Событие")
                # 1) notification
                notif_text = (
                    f"🔔 <b>Сегодня {type_label.lower()}!</b>\n\n"
                    f"{emoji} <b>{e['name']}</b> — {e['day']:02d}.{e['month']:02d}"
                )
                try:
                    await ctx.bot.send_message(
                        chat_id=user_id,
                        text=notif_text,
                        parse_mode="HTML",
                    )
                    # 2) greeting suggestion
                    greeting = await greetings.generate_greeting(e["name"], e["type"])
                    await ctx.bot.send_message(
                        chat_id=user_id,
                        text=f"💌 <b>Вариант поздравления:</b>\n\n<i>{greeting}</i>",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "🔄 Другой вариант",
                                callback_data=f"regen_{e['id']}",
                            )],
                        ]),
                    )
                except Exception:
                    logger.warning("Could not send notification to user %s", user_id)


# ── Regenerate greeting callback (works outside conversation) ────────
async def regen_greeting_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    event_id = int(q.data.split("_", 1)[1])
    event = storage.get_event(q.from_user.id, event_id)
    if not event:
        await q.edit_message_text("⚠️ Событие не найдено.")
        return
    greeting = await greetings.generate_greeting(event["name"], event["type"])
    await q.edit_message_text(
        f"💌 <b>Вариант поздравления:</b>\n\n<i>{greeting}</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔄 Другой вариант",
                callback_data=f"regen_{event['id']}",
            )],
        ]),
    )


# ── Post-init: set bot commands & menu button ────────────────────────
async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("cancel", "Отмена"),
    ])
    # Schedule daily check at 09:00 Moscow time (UTC+3 → UTC 06:00)
    app.job_queue.run_daily(
        _daily_check,
        time=datetime.time(hour=6, minute=0, second=0),  # 09:00 MSK
        name="daily_event_check",
    )


# ── Main ─────────────────────────────────────────────────────────────
def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set. Create bot/.env with BOT_TOKEN=<your token>")

    app = Application.builder().token(token).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_cb, pattern=r"^(add|list|edit)$"),
                CallbackQueryHandler(cancel_cb, pattern=r"^main$"),
            ],
            ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_name),
                CallbackQueryHandler(cancel_cb, pattern=r"^main$"),
            ],
            ADD_DAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_day),
                CallbackQueryHandler(cancel_cb, pattern=r"^main$"),
            ],
            ADD_MONTH: [
                CallbackQueryHandler(add_month_cb, pattern=r"^(month_\d+|cancel)$"),
            ],
            ADD_TYPE: [
                CallbackQueryHandler(add_type_cb, pattern=r"^(type_\w+|cancel)$"),
            ],
            EDIT_PICK: [
                CallbackQueryHandler(edit_pick_cb, pattern=r"^(pick_\d+|main)$"),
            ],
            EDIT_FIELD: [
                CallbackQueryHandler(edit_field_cb, pattern=r"^(ef_\w+|edit)$"),
            ],
            EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name),
                CallbackQueryHandler(cancel_cb, pattern=r"^edit$"),
            ],
            EDIT_DAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_day),
                CallbackQueryHandler(cancel_cb, pattern=r"^edit$"),
            ],
            EDIT_MONTH: [
                CallbackQueryHandler(edit_month_cb, pattern=r"^(month_\d+|cancel)$"),
            ],
            EDIT_TYPE: [
                CallbackQueryHandler(edit_type_cb, pattern=r"^(type_\w+|cancel)$"),
            ],
            DELETE_CONFIRM: [
                CallbackQueryHandler(delete_confirm_cb, pattern=r"^del_(yes|no)$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
        ],
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(regen_greeting_cb, pattern=r"^regen_\d+$"))

    logger.info("Bot started — polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
