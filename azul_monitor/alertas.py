"""Envio de alertas: console, Telegram, e-mail e ntfy.sh (notificação no celular)."""

import logging
import smtplib
from email.message import EmailMessage

import httpx

from .config import Config

log = logging.getLogger(__name__)


class Notificador:
    def __init__(self, config: Config):
        self.config = config

    def canais(self) -> list[str]:
        c = self.config
        canais = ["console"]
        if c.telegram_token and c.telegram_chat_id:
            canais.append("telegram")
        if c.smtp_host and c.email_destino:
            canais.append("email")
        if c.ntfy_topic:
            canais.append("ntfy")
        return canais

    def enviar(self, titulo: str, mensagem: str) -> None:
        log.warning("ALERTA: %s\n%s", titulo, mensagem)
        for canal in self.canais()[1:]:
            try:
                getattr(self, f"_enviar_{canal}")(titulo, mensagem)
            except Exception:
                log.exception("Falha ao enviar alerta via %s", canal)

    def _enviar_telegram(self, titulo: str, mensagem: str) -> None:
        c = self.config
        httpx.post(
            f"https://api.telegram.org/bot{c.telegram_token}/sendMessage",
            json={"chat_id": c.telegram_chat_id, "text": f"✈️ {titulo}\n\n{mensagem}"},
            timeout=20,
        ).raise_for_status()

    def _enviar_email(self, titulo: str, mensagem: str) -> None:
        c = self.config
        msg = EmailMessage()
        msg["Subject"] = titulo
        msg["From"] = c.smtp_user or c.email_destino
        msg["To"] = c.email_destino
        msg.set_content(mensagem)
        with smtplib.SMTP(c.smtp_host, c.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if c.smtp_user:
                smtp.login(c.smtp_user, c.smtp_password or "")
            smtp.send_message(msg)

    def _enviar_ntfy(self, titulo: str, mensagem: str) -> None:
        httpx.post(
            f"https://ntfy.sh/{self.config.ntfy_topic}",
            content=mensagem.encode(),
            headers={"Title": titulo.encode("utf-8"), "Tags": "airplane"},
            timeout=20,
        ).raise_for_status()
