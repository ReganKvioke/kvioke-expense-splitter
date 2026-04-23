from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot.utils.constants import CATEGORY_EMOJIS, CURRENCY_TIMEZONES


def _parse_iso(iso_timestamp: str) -> datetime:
    dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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


def _tz_for_currency(currency: str) -> ZoneInfo:
    """Return the ZoneInfo for a currency, falling back to UTC."""
    tz_name = CURRENCY_TIMEZONES.get(currency, "UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def fmt_datetime_local(iso_timestamp: str, currency: str) -> str:
    """Short datetime converted to the local timezone for the given currency.
    Format: '14 Apr 18:30'  (same width as fmt_datetime_compact)."""
    try:
        utc_dt = _parse_iso(iso_timestamp)
        local_dt = utc_dt.astimezone(_tz_for_currency(currency))
        return local_dt.strftime("%d %b %H:%M")
    except (ValueError, Exception):
        return iso_timestamp


def fmt_datetime_full_local(iso_timestamp: str, currency: str) -> str:
    """Full datetime converted to the local timezone for the given currency.
    Format: '14 Apr 2026 18:30 JST'."""
    try:
        utc_dt = _parse_iso(iso_timestamp)
        local_dt = utc_dt.astimezone(_tz_for_currency(currency))
        return f"{local_dt.strftime('%d %b %Y %H:%M')} {tz_abbrev(currency)}"
    except (ValueError, Exception):
        return iso_timestamp


# Fallback abbreviations for timezones that Python's zoneinfo returns as "+07"/"+08"
_TZ_ABBREV_OVERRIDE: dict[str, str] = {
    "Asia/Singapore":    "SGT",
    "Asia/Kuala_Lumpur": "MYT",
    "Asia/Bangkok":      "ICT",
    "Asia/Ho_Chi_Minh":  "ICT",
}


def tz_abbrev(currency: str) -> str:
    """Return the timezone abbreviation for a currency (e.g. 'JST', 'SGT')."""
    tz_name = CURRENCY_TIMEZONES.get(currency, "UTC")
    if tz_name in _TZ_ABBREV_OVERRIDE:
        return _TZ_ABBREV_OVERRIDE[tz_name]
    try:
        tz = _tz_for_currency(currency)
        # Use a fixed reference time to get the abbreviation without DST ambiguity
        sample = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).astimezone(tz)
        return sample.strftime("%Z")
    except Exception:
        return "UTC"


def fmt_category(cat: str) -> str:
    emoji = CATEGORY_EMOJIS.get(cat, "")
    return f"{emoji} {cat.capitalize()}" if emoji else cat.capitalize()


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def fmt_balance_line(name: str, net: float, is_worst: bool = False) -> str:
    if net < -0.005:
        icon = "🔴" if is_worst else "🟡"
        return f"{icon} {name} owes {fmt_sgd(abs(net))}" + (" (owes the most)" if is_worst else "")
    elif net > 0.005:
        return f"🟢 {name} is owed {fmt_sgd(net)}"
    else:
        return f"⚪ {name} is settled up"
