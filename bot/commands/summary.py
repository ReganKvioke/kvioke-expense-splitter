import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.utils.format import fmt_sgd, fmt_amount, fmt_datetime_local, fmt_category, tz_abbrev

logger = logging.getLogger(__name__)


def _since_iso(period: str) -> str | None:
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    else:
        return None
    return start.isoformat()


@require_auth
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    group_chat_id = str(update.effective_chat.id)

    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await update.message.reply_text(
            "⛔ No active trip. Use /tripstart <name> [currency] to begin a trip first."
        )
        return

    trip_id = active_trip["id"]
    trip_name = active_trip["name"]
    arg = (context.args[0].lower() if context.args else "week")

    try:
        if arg == "category":
            rows = await run_in_executor(queries.get_expenses_by_category, group_chat_id, trip_id)
            if not rows:
                await update.message.reply_text(f"No expenses recorded yet for *{trip_name}*.", parse_mode="Markdown")
                return

            lines = [f"📊 *{trip_name} — Spending by category:*\n"]
            for row in rows:
                lines.append(
                    f"• {fmt_category(row['category'])}: {fmt_sgd(row['total_sgd'])} ({row['count']} expense{'s' if row['count'] != 1 else ''})"
                )
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
            return

        since = _since_iso(arg)
        if since is None:
            await update.message.reply_text(
                "Unknown period. Use: today, week (default), month, or category."
            )
            return

        expenses = await run_in_executor(queries.get_expenses_for_group, group_chat_id, since, trip_id)

        if not expenses:
            label_map = {"today": "today", "week": "the last 7 days", "month": "the last 30 days"}
            await update.message.reply_text(
                f"No expenses in *{trip_name}* for {label_map.get(arg, arg)}.",
                parse_mode="Markdown",
            )
            return

        currency = active_trip["default_currency"]
        tz = tz_abbrev(currency)
        total = sum(e["amount_sgd"] for e in expenses)
        label_map = {"today": "Today", "week": "Last 7 days", "month": "Last 30 days"}
        lines = [f"📋 *{trip_name} · {label_map.get(arg, arg)} — {fmt_sgd(total)} total ({tz}):*\n"]

        for e in expenses:
            amt = fmt_amount(e['amount'], e['currency'])
            sgd_suffix = f" ({fmt_sgd(e['amount_sgd'])})" if e['currency'] != "SGD" else ""
            line = (
                f"• {fmt_datetime_local(e['created_at'], currency)} | {e['description']} | "
                f"{amt}{sgd_suffix} | paid by {e['paid_by_name']} | {fmt_category(e['category'])}"
            )
            lines.append(line)

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    except Exception as exc:
        logger.error("Summary error: %s", exc)
        await update.message.reply_text("❌ Could not load summary. Please try again.")
