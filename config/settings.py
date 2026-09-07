"""Load project-local configuration; validate only credentials a command uses."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
OUTPUT_DIR: Path = PROJECT_ROOT / "outputs"
load_dotenv(PROJECT_ROOT / ".env")


def require_env(name: str) -> str:
    """Return a nonempty configured value; raise ValueError when missing."""
    try:
        value = os.environ[name].strip()
    except KeyError:
        raise ValueError(f"Set {name} in the project .env file.") from None
    if not value or value.startswith("your_") or ".example" in value:
        raise ValueError(f"Set {name} in the project .env file.")
    return value


def get_serpapi_key() -> str:
    """Return the SERPAPI_KEY from the environment."""
    return require_env("SERPAPI_KEY")
