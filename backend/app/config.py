import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def db_path() -> str:
    return env("DATABASE_URL", "sqlite:///./trustpay.db").replace("sqlite:///", "", 1)


def signing_key() -> bytes:
    key = env("DECISION_SIGNING_KEY")
    if len(key) < 16:  # fail closed: no key, no tokens
        raise RuntimeError("DECISION_SIGNING_KEY missing or too short")
    return key.encode()
