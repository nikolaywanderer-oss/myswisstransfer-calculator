# Telegram Bot

A Python Telegram bot built with [python-telegram-bot](https://python-telegram-bot.org/) v22.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with command list |
| `/help` | Help text and usage |
| `/echo <text>` | Repeats text back |
| `/about` | Info about the bot |

Any non-command message is also echoed back.

## Adding New Commands

1. Add a handler function in `bot/src/handlers.py`
2. Register it in `bot/src/bot.py` with `app.add_handler(CommandHandler("yourcommand", your_handler))`

## Structure

```
bot/
  src/
    bot.py       # Entry point, sets up Application and registers handlers
    handlers.py  # All command and message handler functions
```
