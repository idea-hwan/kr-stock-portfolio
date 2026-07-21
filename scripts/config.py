import os
from pathlib import Path


def _load_dotenv(env_path: Path) -> None:
    """
    Minimal .env loader (no external dependency).
    Reads KEY=VALUE lines and sets them into `os.environ` if not already set.
    """
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


# Load local env on import, so other modules can just call get_dart_api_key().
_BASE_DIR = Path(__file__).resolve().parent.parent
_load_dotenv(_BASE_DIR / ".env")


def get_dart_api_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DART_API_KEY is not set. Create a .env file in the project root "
            "with `DART_API_KEY=...` or export it in your shell."
        )
    return key

