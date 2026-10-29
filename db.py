import json
import os
from config import SENT_EMAILS_PATH


def _load() -> list[dict]:
    if not os.path.exists(SENT_EMAILS_PATH):
        return []
    with open(SENT_EMAILS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(records: list[dict]) -> None:
    os.makedirs(os.path.dirname(SENT_EMAILS_PATH), exist_ok=True)
    with open(SENT_EMAILS_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def is_sent(domain: str) -> bool:
    records = _load()
    return any(r["domain"] == domain for r in records)


def mark_sent(domain: str, email: str, company: str) -> None:
    records = _load()
    records.append({"domain": domain, "email": email, "company": company})
    _save(records)


def get_all() -> list[dict]:
    return _load()
