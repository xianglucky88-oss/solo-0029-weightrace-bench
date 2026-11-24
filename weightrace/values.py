from datetime import date, datetime, timezone
import re

from .errors import Problem


def fields(value, *required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(required) | set(optional):
        raise Problem("fields", "字段不完整或含未知字段", expected=[*required, *(f"{name}?" for name in optional)])
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise Problem("boolean", f"{label}须为布尔值")
    return value


def identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", value):
        raise Problem("identifier", f"{label}须为 1 至 48 位字母、数字、下划线或短横线，且以字母或数字开头")
    return value


def integer(value, label, minimum=0, maximum=1_000_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Problem("integer", f"{label}须为 {minimum} 至 {maximum} 的整数")
    return value


def text(value, label, maximum=180):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise Problem("text", f"{label}须为 1 至 {maximum} 字")
    return value.strip()


def day(value):
    try:
        parsed = date.fromisoformat(value)
        if value == parsed.isoformat():
            return value
    except (TypeError, ValueError):
        pass
    raise Problem("date", "日期须为 YYYY-MM-DD")


def instant(value):
    try:
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
            raise ValueError
        return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise Problem("time", "采集时间须为 UTC 整秒，如 2026-09-18T09:00:00Z") from None


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
