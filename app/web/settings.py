"""Runtime settings for the O-Mica web app.

Reads the OpenAI key/model from the same .streamlit/secrets.toml the Streamlit
app uses (so there's one place to configure), with environment variables taking
precedence. The selected project is per-session UI state, defaulting to general.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

DEFAULT_MODEL = "gpt-5.2"
PROJECTS = ["general", "jiuzhou", "research"]


@lru_cache(maxsize=1)
def _secrets() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    try:
        with SECRETS_PATH.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or _secrets().get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY not found. Set it in .streamlit/secrets.toml or the "
            "OPENAI_API_KEY environment variable."
        )
    return key


def model() -> str:
    return os.environ.get("OPENAI_MODEL") or _secrets().get("OPENAI_MODEL", DEFAULT_MODEL)
