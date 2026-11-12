import re

PATTERNS = {
    "ignore_instructions": r"(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)?\s*(rules|instructions|policy|limits)",
    "forced_purchase": r"you\s+(must|should|have to)\s+(now\s+)?(buy|purchase|pay|check\s*out|order)",
    "override": r"\b(override|bypass)\b.{0,30}\b(limit|rule|policy|approval|mandate)",
    "hide_from_user": r"(do\s+not|don't|never)\s+(tell|inform|ask|notify)\s+the\s+user",
    "skip_confirmation": r"without\s+(asking|confirmation|approval)",
    "new_instructions": r"\b(new|updated)\s+(instructions|system\s+prompt)\b",
    "role_hijack": r"\b(system\s+prompt|act\s+as|you\s+are\s+now)\b",
}


def scan(*texts: str) -> list[str]:
    blob = " ".join(t for t in texts if t).lower()
    return [name for name, pat in PATTERNS.items() if re.search(pat, blob)]
