"""Bot entry point — build application and register all handlers."""
import logging
import os

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler

from bot.db.schema import init_db
from bot.commands.add import build_add_handler
from bot.commands.balances import cmd_balances
from bot.commands.delete import build_delete_handler
from bot.commands.quickadd import cmd_quickadd
from bot.commands.summary import cmd_summary
from bot.commands.trips import build_tripstart_handler, cmd_tripend, cmd_tripsummary, cmd_tripjoin
from bot.commands.tripdelete import build_tripdelete_handler
from bot.commands.tripdeleteforce import build_tripdeleteforce_handler
from bot.commands.orphans import build_orphans_handler
from bot.commands.guestdelete import build_guestdelete_handler
from bot.commands.guestmerge import build_guestmerge_handler
from bot.commands.settle import build_settle_handler
from bot.commands.undo import build_undo_handler
from bot.commands.edit import build_edit_handler
from bot.commands.settlements import cmd_settlements
from bot.commands.exporthtml import cmd_exporthtml
from bot.commands.help import cmd_help
from bot.middleware.auth import cmd_start, cmd_revoke, cmd_users

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in environment")

    if not os.getenv("BOT_PASSWORD"):
        raise RuntimeError("BOT_PASSWORD is not set in environment")

    init_db()

    app = Application.builder().token(token).build()

    # Auth commands (no auth middleware — /start is the entry point)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("users", cmd_users))

    # Expense commands (auth middleware applied inside each handler)
    app.add_handler(build_add_handler())
    app.add_handler(build_delete_handler())
    app.add_handler(CommandHandler("quickadd", cmd_quickadd))
    app.add_handler(CommandHandler("balances", cmd_balances))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(build_settle_handler())
    app.add_handler(build_undo_handler())
    app.add_handler(build_edit_handler())
    app.add_handler(CommandHandler("settlements", cmd_settlements))
    app.add_handler(CommandHandler("exporthtml", cmd_exporthtml))
    app.add_handler(build_tripstart_handler())
    app.add_handler(CommandHandler("tripend", cmd_tripend))
    app.add_handler(CommandHandler("tripjoin", cmd_tripjoin))
    app.add_handler(CommandHandler("tripsummary", cmd_tripsummary))
    app.add_handler(build_tripdelete_handler())
    app.add_handler(build_tripdeleteforce_handler())
    app.add_handler(build_orphans_handler())
    app.add_handler(build_guestdelete_handler())
    app.add_handler(build_guestmerge_handler())
    app.add_handler(CommandHandler("help", cmd_help))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
