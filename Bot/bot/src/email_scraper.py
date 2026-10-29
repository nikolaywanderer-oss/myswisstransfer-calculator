import logging
import re
import aiohttp

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]{2,}")

# Extensions / patterns that are never real contact emails
_SKIP_PATTERNS = re.compile(
    r"\.(png|jpg|jpeg|gif|svg|webp|ico|css|js|woff|ttf|eot|pdf|zip)$"
    r"|sentry|example\.|@schema|@context|noreply|no-reply|@w3\.org",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MySwissTransferBot/1.0; "
        "+https://myswisstransfer.com)"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de,en;q=0.8",
}

_CONTACT_PATHS = ["", "/contact", "/kontakt", "/about", "/impressum", "/imprint"]


def _pick_best_email(candidates: list[str], domain: str) -> str | None:
    """Prefer emails on the same domain; prefer info/contact prefixes."""
    same_domain = [e for e in candidates if domain in e.lower()]
    pool = same_domain or candidates

    priority = ["info@", "contact@", "hello@", "mail@", "office@", "hallo@"]
    for prefix in priority:
        for e in pool:
            if e.lower().startswith(prefix):
                return e
    return pool[0] if pool else None


async def _scrape_emails_from_url(session: aiohttp.ClientSession, url: str) -> list[str]:
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True, ssl=False) as resp:
            if resp.status != 200:
                return []
            # Only read up to 200 KB to keep it fast
            html = await resp.content.read(200_000)
            text = html.decode("utf-8", errors="ignore")
    except Exception as e:
        logger.debug("Scrape error for %s: %s", url, e)
        return []

    found = EMAIL_RE.findall(text)
    return [e for e in found if not _SKIP_PATTERNS.search(e)]


async def find_email(url: str, domain: str) -> str:
    """
    Try to find a real contact email by scraping the site's homepage and
    common contact pages. Falls back to info@<domain> if nothing is found.
    """
    base = f"https://{domain}"
    urls_to_try = [url] + [base + path for path in _CONTACT_PATHS if path]

    async with aiohttp.ClientSession() as session:
        for target in urls_to_try:
            emails = await _scrape_emails_from_url(session, target)
            if emails:
                best = _pick_best_email(emails, domain)
                if best:
                    logger.info("Found email %s on %s", best, target)
                    return best

    fallback = f"info@{domain}"
    logger.info("No email found for %s — using fallback %s", domain, fallback)
    return fallback
