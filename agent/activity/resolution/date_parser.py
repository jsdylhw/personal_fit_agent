"""日期 / 范围 / 排序参数解析工具."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any


def date_argument(args: dict[str, Any], *, today: date | None) -> str | None:
    value = args.get("date_local") or args.get("date")
    if value:
        return _resolve_relative_date(str(value), today=today)
    date_range = _range_text_argument(args)
    if _mentions_today(date_range) or _mentions_yesterday(date_range):
        return _resolve_relative_date(date_range, today=today)
    return None


def date_range_arguments(args: dict[str, Any], *, today: date | None) -> tuple[str, str] | None:
    current = today or date.today()
    if args.get("start_date") and args.get("end_date"):
        return str(args["start_date"]), str(args["end_date"])
    if args.get("start_date"):
        return str(args["start_date"]), current.isoformat()
    if args.get("end_date"):
        return "0001-01-01", str(args["end_date"])

    date_range = _range_text_argument(args)
    relative_range = _resolve_relative_date_range(date_range, today=current)
    if relative_range:
        return relative_range
    if _mentions_today(date_range) or _mentions_yesterday(date_range):
        resolved = _resolve_relative_date(date_range, today=current)
        return resolved, resolved

    days = args.get("days")
    if days is not None:
        count = max(1, int(days))
        start = current - timedelta(days=count - 1)
        return start.isoformat(), current.isoformat()

    return None


def is_all_activities_range(args: dict[str, Any]) -> bool:
    text = " ".join(
        str(args.get(key) or "")
        for key in ("range", "date_range", "time_range", "range_type", "relative_range", "scope", "type")
    ).lower()
    return any(token in text for token in ("all_history", "all activities", "all", "全部", "所有", "历史活动"))


def order_argument(args: dict[str, Any], *, reason: str = "") -> str:
    text = str(
        args.get("order")
        or args.get("match")
        or args.get("position")
        or ""
    ).strip().lower()
    combined = f"{text} {reason}".lower()
    if any(token in combined for token in ("first", "earliest", "oldest", "chronological", "asc", "ascending", "第一个", "最早", "最前")):
        return "earliest"
    return "latest"


def activity_index_from_text(text: str) -> int | None:
    normalized = str(text or "")
    digit_match = re.search(r"第\s*(\d+)\s*个", normalized)
    if digit_match:
        return int(digit_match.group(1))

    chinese_digits = {
        "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    chinese_match = re.search(r"第\s*([一二两三四五六七八九十])\s*个", normalized)
    if chinese_match:
        return chinese_digits.get(chinese_match.group(1))
    return None


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _range_text_argument(args: dict[str, Any]) -> str:
    return str(
        args.get("date_range")
        or args.get("time_range")
        or args.get("range_type")
        or args.get("range_description")
        or args.get("relative_range")
        or args.get("range")
        or ""
    ).strip().lower()


def _resolve_relative_date_range(value: str, *, today: date) -> tuple[str, str] | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None

    if normalized in {"last_month", "previous_month"} or "上个月" in normalized or "上月" in normalized:
        first_this_month = today.replace(day=1)
        last_previous_month = first_this_month - timedelta(days=1)
        first_previous_month = last_previous_month.replace(day=1)
        return first_previous_month.isoformat(), last_previous_month.isoformat()

    if normalized in {"this_month", "current_month"} or "这个月" in normalized or "本月" in normalized:
        first = today.replace(day=1)
        return first.isoformat(), today.isoformat()

    if normalized in {"last_week", "previous_week"} or "上周" in normalized or "上一周" in normalized:
        start_this_week = today - timedelta(days=today.weekday())
        start_previous_week = start_this_week - timedelta(days=7)
        end_previous_week = start_this_week - timedelta(days=1)
        return start_previous_week.isoformat(), end_previous_week.isoformat()

    if normalized in {"this_week", "current_week"} or "这周" in normalized or "本周" in normalized:
        start = today - timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()

    return None


def _resolve_relative_date(value: str, *, today: date | None) -> str:
    current = today or date.today()
    normalized = value.strip().lower()
    if _mentions_today(normalized):
        return current.isoformat()
    if _mentions_yesterday(normalized):
        return (current - timedelta(days=1)).isoformat()
    return value


def _mentions_today(value: str) -> bool:
    return "today" in value or "今天" in value


def _mentions_yesterday(value: str) -> bool:
    return "yesterday" in value or "昨天" in value
