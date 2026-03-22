"""Inline calendar date picker component for Telegram bots.

Usage:
    from datepicker import DatePicker

    # Month+day only (no year row):
    picker = DatePicker(prefix="adate", show_year=False)

    # Full date with year navigation:
    picker = DatePicker(prefix="from", show_year=True)

    # Build keyboard:
    kb = picker.build(year, month)

    # Handle callback in a conversation handler:
    result = picker.parse(callback_data)
    # result is one of:
    #   ("noop", year, month)
    #   ("navigate", new_year, new_month)
    #   ("day", year, month, day)
"""

import calendar

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MONTH_NAMES_RU = [
    "", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
]

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class DatePicker:
    """Reusable inline calendar widget."""

    def __init__(self, prefix: str, show_year: bool = True):
        self.prefix = prefix
        self.show_year = show_year

    def build(self, year: int, month: int) -> InlineKeyboardMarkup:
        """Build inline keyboard for the given year/month."""
        p = self.prefix
        rows = []

        if self.show_year:
            rows.append([
                InlineKeyboardButton("◀", callback_data=f"{p}:yprev:{year}:{month}"),
                InlineKeyboardButton(str(year), callback_data="noop"),
                InlineKeyboardButton("▶", callback_data=f"{p}:ynext:{year}:{month}"),
            ])

        rows.append([
            InlineKeyboardButton("◀", callback_data=f"{p}:prev:{year}:{month}"),
            InlineKeyboardButton(MONTH_NAMES_RU[month], callback_data="noop"),
            InlineKeyboardButton("▶", callback_data=f"{p}:next:{year}:{month}"),
        ])

        rows.append([
            InlineKeyboardButton(d, callback_data="noop") for d in WEEKDAYS_RU
        ])

        for week in calendar.monthcalendar(year, month):
            row = []
            for day in week:
                if day == 0:
                    row.append(InlineKeyboardButton(" ", callback_data="noop"))
                else:
                    row.append(InlineKeyboardButton(
                        str(day),
                        callback_data=f"{p}:day:{year}:{month}:{day}",
                    ))
            rows.append(row)

        return InlineKeyboardMarkup(rows)

    def parse(self, data: str) -> tuple:
        """Parse callback_data and return action tuple.

        Returns:
            ("noop", year, month)              — no-op click
            ("navigate", new_year, new_month)  — month/year changed
            ("day", year, month, day)          — day selected
        """
        parts = data.split(":")
        action = parts[1]
        year, month = int(parts[2]), int(parts[3])

        if action == "noop":
            return ("noop", year, month)

        if action in ("prev", "next"):
            month += -1 if action == "prev" else 1
            if month > 12:
                month = 1
                year += 1
            elif month < 1:
                month = 12
                year -= 1
            return ("navigate", year, month)

        if action in ("yprev", "ynext"):
            year += -1 if action == "yprev" else 1
            return ("navigate", year, month)

        if action == "day":
            day = int(parts[4])
            return ("day", year, month, day)

        return ("noop", year, month)
