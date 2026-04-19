from datetime import datetime, timezone

from bot.utils.constants import CATEGORY_EMOJIS


def _parse_iso(iso_timestamp: str) -> datetime:
    return datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))


def fmt_sgd(amount: float) -> str:
    return f"SGD {amount:.2f}"


def fmt_amount(amount: float, currency: str) -> str:
    """Format an amount in its original currency."""
    if currency in ("JPY", "KRW", "IDR", "VND"):
        return f"{currency} {amount:,.0f}"
    return f"{currency} {amount:.2f}"


def fmt_date(iso_timestamp: str) -> str:
    try:
        return _parse_iso(iso_timestamp).strftime("%d %b %Y")
    except ValueError:
        return iso_timestamp


def fmt_datetime(iso_timestamp: str) -> str:
    try:
        return _parse_iso(iso_timestamp).strftime("%d %b %Y %H:%M UTC")
    except ValueError:
        return iso_timestamp


def fmt_datetime_compact(iso_timestamp: str) -> str:
    """Short format for space-constrained contexts, e.g. inline keyboard buttons."""
    try:
        return _parse_iso(iso_timestamp).strftime("%d %b %H:%M")
    except ValueError:
        return iso_timestamp


def fmt_category(cat: str) -> str:
    emoji = CATEGORY_EMOJIS.get(cat, "")
    return f"{emoji} {cat.capitalize()}" if emoji else cat.capitalize()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fmt_balance_line(name: str, net: float, is_worst: bool = False) -> str:
    if net < -0.005:
        icon = "🔴" if is_worst else "🟡"
        return f"{icon} {name} owes {fmt_sgd(abs(net))}" + (" (owes the most)" if is_worst else "")
    elif net > 0.005:
        return f"🟢 {name} is owed {fmt_sgd(net)}"
    else:
        return f"⚪ {name} is settled up"
