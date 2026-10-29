import logging
import re
import requests
from urllib.parse import urlparse
from config import SERPAPI_API_KEY

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"


def _extract_domain(url: str) -> str:
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    domain = re.sub(r"^www\.", "", domain)
    return domain.lower()


def _extract_email_from_snippet(snippet: str) -> str | None:
    match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", snippet)
    return match.group(0) if match else None


def search_companies(query: str, num: int = 10) -> list[dict]:
    params = {
        "engine": "google",
        "q": query,
        "num": num,
        "api_key": SERPAPI_API_KEY,
    }
    try:
        resp = requests.get(SERPAPI_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("SerpAPI error: %s", e)
        return []

    results = []
    for item in data.get("organic_results", [])[:num]:
        url = item.get("link", "")
        domain = _extract_domain(url)
        if not domain:
            continue
        snippet = item.get("snippet", "")
        email = _extract_email_from_snippet(snippet)
        company = item.get("title", domain)
        results.append({
            "domain": domain,
            "url": url,
            "company": company,
            "email": email,
            "snippet": snippet,
        })
    return results
