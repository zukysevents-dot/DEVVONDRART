"""Scoring leadů přes Claude API (Messages API).

Pro každý nový lead se zavolá model, který vrátí striktní JSON:
    {"score": 1-10, "reason": "...", "outreach_draft": "..."}
Profil studia (config/profile.md) se vkládá do system promptu. Výstup je bezpečně
parsovaný; rate-limit a přechodné chyby se opakují s exponenciálním backoffem.

Volání API je za injektovatelnou funkcí `complete_fn(system, user) -> str`, takže
jádro (prompt, parsování, retry) jde testovat bez sítě a bez API klíče.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from src.config import Settings
from src.models import Lead

logger = logging.getLogger(__name__)

CompleteFn = Callable[[str, str], str]

MAX_TOKENS = 1024


class RetryableError(Exception):
    """Přechodná chyba (rate-limit, timeout, 5xx) — má smysl opakovat."""


@dataclass
class Score:
    score: int
    reason: str
    outreach_draft: str


SYSTEM_TEMPLATE = """\
Jsi asistent brandingového studia a hodnotíš potenciální klienty (leady).

Profil studia (komu se chceme hodit):
---
{profile}
---

Úkol: pro zadanou firmu posuď, jak dobře sedí jako klient studia — podle oboru,
velikosti a pravděpodobné potřeby vizuální identity. Nová / rozjíždějící se značka
v relevantním B2C oboru = vyšší skóre. Velká korporace, ryze B2B nebo obor mimo
záběr = nižší skóre.

Odpověz VÝHRADNĚ jedním JSON objektem, bez markdownu a bez textu navíc, přesně v tomto tvaru:
{{"score": <celé číslo 1-10>, "reason": "<jedna věta česky, proč se (ne)hodí>", "outreach_draft": "<krátký, lidský první e-mail česky na míru té firmě>"}}"""


def build_user_prompt(lead: Lead) -> str:
    parts = [
        f"Název: {lead.name}",
        f"Obor (náš popisek): {lead.obor or '-'}",
        f"CZ-NACE: {', '.join(lead.nace) or '-'}",
        f"Region: {lead.region or '-'}",
        f"Datum vzniku: {lead.date.isoformat() if lead.date else '-'}",
        f"Odkaz: {lead.url or '-'}",
    ]
    return "\n".join(parts)


def parse_score(raw: str) -> Optional[Score]:
    """Bezpečně vytáhne JSON objekt z odpovědi a zvaliduje ho. None = nepovedlo se."""
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "score" not in data:
        return None
    try:
        score = int(data["score"])
    except (TypeError, ValueError):
        return None
    score = max(1, min(10, score))
    return Score(
        score=score,
        reason=str(data.get("reason", "")).strip(),
        outreach_draft=str(data.get("outreach_draft", "")).strip(),
    )


class Scorer:
    """Hodnotí leady přes injektovatelnou `complete_fn`."""

    def __init__(
        self,
        profile_text: str,
        complete_fn: CompleteFn,
        max_retries: int = 3,
        backoff: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.system_prompt = SYSTEM_TEMPLATE.format(profile=profile_text)
        self.complete_fn = complete_fn
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings, profile_text: str, **kwargs) -> "Scorer":
        """Sestaví Scorer napojený na živé Claude API."""
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        model = settings.anthropic_model

        def complete(system: str, user: str) -> str:
            try:
                msg = client.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
            except (
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.InternalServerError,
            ) as exc:
                raise RetryableError(str(exc)) from exc
            return "".join(
                block.text for block in msg.content if getattr(block, "type", "") == "text"
            )

        return cls(profile_text, complete, **kwargs)

    def score_lead(self, lead: Lead) -> Optional[Score]:
        """Vrátí Score, nebo None když se to ani po retry nepovede."""
        user = build_user_prompt(lead)
        for attempt in range(self.max_retries):
            try:
                raw = self.complete_fn(self.system_prompt, user)
            except RetryableError as exc:
                logger.warning("Scoring '%s' — přechodná chyba (%s), pokus %d/%d.",
                               lead.name, exc, attempt + 1, self.max_retries)
                self._backoff(attempt)
                continue
            parsed = parse_score(raw)
            if parsed is not None:
                return parsed
            logger.warning("Scoring '%s' — nečitelný JSON, pokus %d/%d.",
                           lead.name, attempt + 1, self.max_retries)
            self._backoff(attempt)
        logger.error("Scoring '%s' se nepovedl, lead zůstane bez skóre.", lead.name)
        return None

    def _backoff(self, attempt: int) -> None:
        if attempt < self.max_retries - 1:
            self.sleep(self.backoff * (2 ** attempt))

    def score_leads(self, leads: list[Lead]) -> list[Lead]:
        """Doplní score/reason/outreach_draft do leadů (in-place) a vrátí je."""
        for lead in leads:
            result = self.score_lead(lead)
            if result is not None:
                lead.score = result.score
                lead.reason = result.reason
                lead.outreach_draft = result.outreach_draft
        return leads
