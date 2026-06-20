"""Webtrh zdroj (Fáze 2) — poptávky na grafiku/design jako inbound leady.

Webtrh nemá funkční RSS (ověřeno) a robots.txt ani podmínky užívání scraping nezakazují
(zakázané je jen systematické *vkládání* obsahu, ne čtení). Proto lehký a slušný přístup:
JEDEN GET na výpis kategorie poptávek, identifikující User-Agent, žádný agresivní crawl.

Z výpisu se u každé poptávky čte název, odkaz, kategorie, rozpočet a relativní datum
("před 9 dny"), které se převede na přibližné datum publikace.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.models import Lead
from src.sources.base import Source

logger = logging.getLogger(__name__)

WEBTRH_BASE = "https://webtrh.cz"
DEFAULT_LISTING = "/poptavky/poptavky-designu-fotografovani-a-videa/"
SOURCE_NAME = "webtrh"
USER_AGENT = "vondrart-leads/0.1 (+https://github.com/zukysevents-dot/DEVVONDRART)"


def parse_relative_date(text: Optional[str], today: date) -> Optional[date]:
    """Převede české relativní datum ("před 9 dny", "včera", "dnes") na přibližné datum."""
    if not text:
        return None
    t = text.strip().lower()
    if "dnes" in t or "chvíl" in t or "hodin" in t or "minut" in t or "sekund" in t:
        return today
    if "včera" in t:
        return today - timedelta(days=1)
    m = re.search(r"před\s+(\d+)\s+(den|dny|dnem|týdn|měsíc|měsíc|let|rok)", t)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("den") or unit.startswith("dny") or unit.startswith("dnem"):
        return today - timedelta(days=n)
    if unit.startswith("týdn"):
        return today - timedelta(weeks=n)
    if unit.startswith("měsíc") or unit.startswith("měsíc"):
        return today - timedelta(days=30 * n)
    return today - timedelta(days=365 * n)  # rok/let


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def parse_listing(html: str, today: date) -> list[Lead]:
    """Vytáhne poptávky z HTML výpisu kategorie a vrátí list Lead."""
    soup = BeautifulSoup(html, "html.parser")
    leads: list[Lead] = []
    for box in soup.select("div.inquiry-box"):
        link = box.find("a", href=True)
        if not link:
            continue
        url = link["href"]
        # vnitřní span je čistý název; .title div může navíc obsahovat badge ("Redakční poptávka")
        title_el = box.select_one(".title span") or box.select_one(".title")
        name = title_el.get_text(" ", strip=True) if title_el else "(bez názvu)"

        kategorie: Optional[str] = None
        rozpocet: Optional[str] = None
        for meta in box.select(".meta div"):
            txt = meta.get_text(" ", strip=True)
            if txt.lower().startswith("kategorie"):
                kategorie = txt.split(":", 1)[-1].strip()
            elif txt.lower().startswith("rozpočet"):
                rozpocet = txt.split(":", 1)[-1].strip()

        created_el = box.select_one(".created")
        created_txt = created_el.get_text(strip=True) if created_el else None

        leads.append(Lead(
            source=SOURCE_NAME,
            external_id=_slug(url),
            name=name,
            nace=[],
            obor=kategorie,
            region=None,  # Webtrh je celostátní
            url=url if url.startswith("http") else WEBTRH_BASE + url,
            date=parse_relative_date(created_txt, today),
            raw={"kategorie": kategorie, "rozpocet": rozpocet, "created": created_txt},
        ))
    return leads


class WebtrhSource(Source):
    """Zdroj inbound poptávek z Webtrhu (jeden GET na výpis kategorie)."""

    name = SOURCE_NAME

    def __init__(
        self,
        listing_path: str = DEFAULT_LISTING,
        max_age_days: int | None = None,
        today: date | None = None,
        client: httpx.Client | None = None,
    ):
        self.listing_path = listing_path
        self.max_age_days = max_age_days
        self.today = today or date.today()
        self.client = client or httpx.Client(
            timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def fetch(self) -> list[Lead]:
        url = self.listing_path if self.listing_path.startswith("http") else WEBTRH_BASE + self.listing_path
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Webtrh nedostupný (%s) — přeskakuji zdroj.", exc)
            return []

        leads = parse_listing(resp.text, today=self.today)

        if self.max_age_days is not None:
            cutoff = self.today - timedelta(days=self.max_age_days)
            # ponech i leady bez data (jsou na první stránce výpisu = čerstvé)
            leads = [lead for lead in leads if lead.date is None or lead.date >= cutoff]

        logger.info("Webtrh: %d poptávek z výpisu.", len(leads))
        return leads
