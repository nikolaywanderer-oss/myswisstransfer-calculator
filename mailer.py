import logging
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import EMAIL_USER, EMAIL_PASS, SMTP_HOST, SMTP_PORT

logger = logging.getLogger(__name__)


async def send_email(to_address: str, subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = to_address

    msg.attach(MIMEText(body, "plain", "utf-8"))

    await aiosmtplib.send(
        msg,
        hostname=SMTP_HOST,
        port=SMTP_PORT,
        username=EMAIL_USER,
        password=EMAIL_PASS,
        start_tls=True,
    )
    logger.info("Email sent to %s | Subject: %s", to_address, subject)
