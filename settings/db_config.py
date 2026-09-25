import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, unquote_plus, urlparse

from settings.settings import Settings

CONFIG_DIR = Path("data")
CONFIG_FILE = CONFIG_DIR / "db_config.json"


def build_database_url(
    usuario: str,
    senha: str,
    host: str,
    porta: int | str,
    database: str,
) -> str:
    user = quote_plus(usuario)
    password = quote_plus(senha)
    return f"postgresql://{user}:{password}@{host}:{porta}/{database}"


def load_config() -> Optional[dict]:
    if not CONFIG_FILE.exists():
        return None
    try:
        with CONFIG_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        required = ("usuario", "senha", "host", "porta", "database")
        if not all(k in data and str(data[k]).strip() for k in required):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def parse_database_url(url: str) -> Optional[dict]:
    if not url or not url.strip():
        return None
    try:
        parsed = urlparse(url)
        if not parsed.hostname or not parsed.path or parsed.path == "/":
            return None
        return {
            "usuario": unquote_plus(parsed.username) if parsed.username else "",
            "senha": unquote_plus(parsed.password) if parsed.password else "",
            "host": parsed.hostname or "",
            "porta": parsed.port or 5432,
            "database": parsed.path.lstrip("/"),
        }
    except Exception:
        return None


def get_database_url() -> str:
    config = load_config()
    if config:
        return build_database_url(
            usuario=config["usuario"],
            senha=config["senha"],
            host=config["host"],
            porta=config["porta"],
            database=config["database"],
        )
    return Settings().DATABASE_URL or ""


def get_form_defaults() -> dict:
    config = load_config()
    if config:
        return {
            "usuario": config.get("usuario", ""),
            "senha": "",
            "host": config.get("host", ""),
            "porta": str(config.get("porta", "5432")),
            "database": config.get("database", ""),
            "has_saved_password": bool(config.get("senha")),
        }
    from_env = parse_database_url(Settings().DATABASE_URL or "")
    if from_env:
        return {
            "usuario": from_env["usuario"],
            "senha": "",
            "host": from_env["host"],
            "porta": str(from_env["porta"]),
            "database": from_env["database"],
            "has_saved_password": bool(from_env["senha"]),
        }
    return {
        "usuario": "",
        "senha": "",
        "host": "",
        "porta": "5432",
        "database": "",
        "has_saved_password": False,
    }
