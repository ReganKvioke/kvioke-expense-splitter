"""Show settlement history for the active trip."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.utils.format import fmt_date, fmt_sgd

logger = logging.getLogger(__name__)


@require_auth
async def cmd_settlements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    group_chat_id = str(update.effective_chat.id)
    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    trip_id = active_trip["id"] if active_trip else None

    settlements = await run_in_executor(
        queries.get_settlements_for_trip, group_chat_id, trip_id
    )

    scope = f"*{active_trip['name']}*" if active_trip else "this group"

    if not settlements:
        await update.message.reply_text(
            f"No settlements recorded for {scope} yet.", parse_mode="Markdown"
        )
        return

    lines = [f"📋 Settlements — {scope}:\n"]
    total = 0.0
    for s in settlements:
        lines.append(
            f"• {fmt_date(s['created_at'])}  "
            f"{s['from_name']} → {s['to_name']}  "
            f"{fmt_sgd(s['amount_sgd'])}"
        )
        total += s["amount_sgd"]

    lines.append(f"\nTotal settled: {fmt_sgd(total)}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
