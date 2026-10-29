import logging
import aiohttp
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OUR_WEBSITE, OUR_SERVICES

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _detect_language(domain: str) -> str:
    if any(domain.endswith(tld) for tld in [".ru", ".kz"]):
        return "Russian"
    if any(domain.endswith(tld) for tld in [".ch", ".de", ".at", ".li"]):
        return "German"
    return "English"


async def generate_email(company: str, domain: str, snippet: str) -> str:
    lang = _detect_language(domain)

    if lang == "Russian":
        system_prompt = (
            "Вы — профессиональный специалист по B2B-продажам. "
            "Пишите деловые письма исключительно на русском языке — грамотно, убедительно и профессионально. "
            "Никогда не используйте английский или немецкий язык. "
            "Будьте конкретны и адаптируйте письмо под бизнес получателя."
        )
        user_prompt = f"""Напишите профессиональное деловое письмо с предложением о партнёрстве на русском языке.

Компания-получатель: {company}
Сайт получателя: https://{domain}
О компании (из поиска): {snippet or "туристическая или транспортная компания"}

Мы — MySwissTransfer, премиальный трансферный сервис в Швейцарии ({OUR_WEBSITE}).
Наш автопарк: {OUR_SERVICES} — идеально подходит для туристических трансферов, деловых поездок и поездок в горы.

Требования:
- Первая строка — тема письма, начиная с «Тема: »
- Пустая строка после темы
- 3–4 абзаца: представление, ценностное предложение, призыв к действию, заключение
- Письмо должно быть адаптировано к бизнесу получателя на основе описания
- Профессиональный, но дружелюбный тон
- Подпись: «Николай, команда MySwissTransfer»
- Язык: ТОЛЬКО русский, никакого английского или немецкого
- НЕ используйте шаблонные заполнители типа [Имя] или [Компания]"""
    else:
        system_prompt = (
            "You are a professional B2B sales writer. "
            "Write concise, warm, and persuasive partnership proposal emails. "
            "Never use generic filler phrases. Be specific to the recipient's business."
        )
        user_prompt = f"""Write a professional B2B partnership proposal email in {lang}.

Recipient company: {company}
Their website: https://{domain}
About them (from search): {snippet or "a travel and transportation company"}

We are MySwissTransfer — a premium Swiss transfer service ({OUR_WEBSITE}).
Our car fleet: {OUR_SERVICES} — perfect for tourist transfers, business trips, and mountain driving in Switzerland.

Requirements:
- Subject line on the first line, prefixed with "Subject: "
- Blank line after subject
- 3-4 short paragraphs: introduction, value proposition, call to action, closing
- Personalize to their business based on the snippet
- Professional but friendly tone
- Sign off as "Nikolai, MySwissTransfer Team"
- Language: {lang}
- Do NOT include placeholders like [Name] or [Company]"""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 600,
        "temperature": 0.7,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(OPENROUTER_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("OpenRouter error %s: %s", resp.status, text)
                raise RuntimeError(f"OpenRouter API error {resp.status}")
            data = await resp.json()

    return data["choices"][0]["message"]["content"].strip()


def parse_subject_body(email_text: str) -> tuple[str, str]:
    lines = email_text.strip().splitlines()
    subject = "Partnership Proposal — MySwissTransfer"
    body_start = 0

    for i, line in enumerate(lines):
        if line.lower().startswith("subject:"):
            subject = line[len("subject:"):].strip()
            body_start = i + 1
            break

    while body_start < len(lines) and lines[body_start].strip() == "":
        body_start += 1

    body = "\n".join(lines[body_start:]).strip()
    return subject, body
