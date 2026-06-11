"""Runtime settings for the O-Mica web app.

Reads the OpenAI key/model from .streamlit/secrets.toml (the secrets file is the
source of truth; environment variables are only a fallback). The path is kept
for backward compatibility with existing local configs. The selected project is
per-session UI state, defaulting to general.
"""

from __future__ import annotations

import os
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]
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
    # The secrets file is the source of truth (matching Streamlit's st.secrets,
    # which ignores environment variables). A stale OPENAI_API_KEY env var would
    # otherwise shadow the working key and cause 401s. Env is only a fallback.
    key = _secrets().get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY not found. Set it in .streamlit/secrets.toml or the "
            "OPENAI_API_KEY environment variable."
        )
    return key


def model() -> str:
    return _secrets().get("OPENAI_MODEL") or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
