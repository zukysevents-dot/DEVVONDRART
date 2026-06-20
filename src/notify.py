"""Notifikace — HTML e-mailový digest (Jinja2) odeslaný přes SMTP.

Denní e-mail v češtině, leady seřazené podle skóre sestupně. Nahoře krátké shrnutí.
Odesílání je za injektovatelnou `smtp_factory`, takže sestavení a renderování jde
testovat bez reálného SMTP serveru. Nic se neodesílá leadům — jen majiteli schránky.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from typing import Callable, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import ROOT, Settings
from src.models import Lead

logger = logging.getLogger(__name__)

TEMPLATES_DIR = ROOT / "templates"
TEMPLATE_NAME = "digest.html.j2"


class NotifyError(Exception):
    pass


@dataclass
class DigestSummary:
    run_date: date
    total_new: int          # kolik nových leadů celkem (před prahem)
    shown: int              # kolik je v digestu
    above_threshold: int    # kolik má skóre >= práh
    threshold: int


def select_for_digest(leads: list[Lead], threshold: int) -> list[Lead]:
    """Seřadí dle skóre sestupně a odfiltruje oskórované pod prahem.
    Neoskórované leady (např. když chybí API klíč) zůstávají a řadí se dolů."""
    kept = [lead for lead in leads if lead.score is None or lead.score >= threshold]
    kept.sort(key=lambda lead: (lead.score if lead.score is not None else -1), reverse=True)
    return kept


def build_summary(run_date: date, all_new: list[Lead], shown: list[Lead], threshold: int) -> DigestSummary:
    return DigestSummary(
        run_date=run_date,
        total_new=len(all_new),
        shown=len(shown),
        above_threshold=sum(1 for lead in all_new if lead.score is not None and lead.score >= threshold),
        threshold=threshold,
    )


def build_subject(summary: DigestSummary) -> str:
    return f"vondrart leady {summary.run_date}: {summary.shown} nových"


def _default_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2", "xml"]),
    )


def render_digest(leads: list[Lead], summary: DigestSummary, env: Environment | None = None) -> str:
    env = env or _default_env()
    return env.get_template(TEMPLATE_NAME).render(leads=leads, summary=summary)


def build_message(html: str, subject: str, settings: Settings) -> EmailMessage:
    sender = settings.digest_from or settings.smtp_user
    if not sender or not settings.digest_to:
        raise NotifyError("Chybí odesílatel (DIGEST_FROM/SMTP_USER) nebo příjemce (DIGEST_TO).")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = settings.digest_to
    msg.set_content("Tento e-mail je v HTML. Otevři ho v klientu s podporou HTML.")
    msg.add_alternative(html, subtype="html")
    return msg


def _default_smtp(settings: Settings) -> smtplib.SMTP:
    if settings.smtp_port == 465:
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=30,
            context=ssl.create_default_context(),
        )
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        if settings.smtp_use_tls:
            smtp.starttls(context=ssl.create_default_context())
    if settings.smtp_user:
        smtp.login(settings.smtp_user, settings.smtp_password or "")
    return smtp


def send_digest(
    html: str,
    subject: str,
    settings: Settings,
    smtp_factory: Optional[Callable[[Settings], smtplib.SMTP]] = None,
) -> None:
    """Sestaví a odešle e-mail přes SMTP."""
    if not settings.smtp_host:
        raise NotifyError("Chybí SMTP_HOST.")
    message = build_message(html, subject, settings)
    smtp = (smtp_factory or _default_smtp)(settings)
    try:
        smtp.send_message(message)
    finally:
        try:
            smtp.quit()
        except Exception:  # quit po odeslání nesmí shodit běh
            pass
