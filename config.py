import os

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SERPAPI_API_KEY = os.environ["SERPAPI_API_KEY"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASS = os.environ["EMAIL_PASS"]

OPENROUTER_MODEL = "meta-llama/llama-3-8b-instruct"
SMTP_HOST = "mail.gmx.net"
SMTP_PORT = 587
OUR_WEBSITE = "https://myswisstransfer.com"
OUR_SERVICES = (
    "Standard Car, Business Sedan, Standard Minivan, "
    "and Business Minivan (Mercedes-Benz V-Class/Vito)"
)

SENT_EMAILS_PATH = "bot/data/sent_emails.json"

DELAY_MIN = 15 * 60
DELAY_MAX = 30 * 60
