import logging
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)
from handlers import (
    start,
    button_handler,
    cancel_command,
    cancel_button_handler,
    status_command,
    report_command,
    draft_action_handler,
    receive_niche,
    fallback,
    error_handler,
    WAITING_FOR_NICHE,
)
from config import TELEGRAM_BOT_TOKEN

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation handler for the niche search flow
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^search$")],
        states={
            WAITING_FOR_NICHE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_niche)
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(draft_action_handler, pattern="^draft:"))
    app.add_handler(CallbackQueryHandler(cancel_button_handler, pattern="^cancel:"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    app.add_error_handler(error_handler)

    logger.info("B2B Outreach Bot started. Polling...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
