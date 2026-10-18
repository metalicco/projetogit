"""Configuração lida de variáveis de ambiente (ou de um arquivo .env)."""

import os
from dataclasses import dataclass
from pathlib import Path


def _carregar_dotenv(caminho: Path = Path(".env")) -> None:
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


@dataclass
class Config:
    db_path: str
    provedor: str  # "azul" ou "simulado"
    headless: bool
    debug_dir: str | None
    pausa_entre_buscas: float
    telegram_token: str | None
    telegram_chat_id: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    email_destino: str | None
    ntfy_topic: str | None


def carregar_config() -> Config:
    _carregar_dotenv()
    env = os.environ.get
    return Config(
        db_path=env("AZUL_DB", "azul_monitor.db"),
        provedor=env("AZUL_PROVEDOR", "azul"),
        headless=env("AZUL_HEADLESS", "1") != "0",
        debug_dir=env("AZUL_DEBUG_DIR") or None,
        pausa_entre_buscas=float(env("AZUL_PAUSA_SEGUNDOS", "8")),
        telegram_token=env("TELEGRAM_TOKEN") or None,
        telegram_chat_id=env("TELEGRAM_CHAT_ID") or None,
        smtp_host=env("SMTP_HOST") or None,
        smtp_port=int(env("SMTP_PORT", "587")),
        smtp_user=env("SMTP_USER") or None,
        smtp_password=env("SMTP_PASSWORD") or None,
        email_destino=env("EMAIL_DESTINO") or None,
        ntfy_topic=env("NTFY_TOPIC") or None,
    )
