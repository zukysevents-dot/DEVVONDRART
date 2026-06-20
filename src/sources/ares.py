"""ARES zdroj (Fáze 1) — nově vzniklé firmy z registru ekonomických subjektů.

Endpoint a tvar filtru jsou ověřené proti živému OpenAPI a API (viz README,
sekce "Otevřené otázky / co ověřit"). Klíčová omezení ARES vyhledávačky:

  * filtr NEumí kraj/okres ani datum vzniku a NEumí řadit podle data,
  * nejmenší územní filtr je obec (kodObce) / městská část (kodMestskeCastiObvodu),
  * jeden dotaz smí vrátit max 1000 záznamů (na CELKOVÝ počet shod).

Proto se dotazuje po segmentech (lokalita × NACE), stáhne se celý segment a
klientsky se ponechají jen firmy s datumVzniku v posledních `max_age_days` dnech.
Kraj se kontroluje klientsky z pole sidlo.kodKraje v odpovědi.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx

from src.config import Locality, Targets
from src.models import Lead
from src.sources.base import Source

logger = logging.getLogger(__name__)

ARES_BASE = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest"
SEARCH_PATH = "/ekonomicke-subjekty/vyhledat"
DETAIL_URL = "https://ares.gov.cz/ekonomicke-subjekty?ico={ico}"

SOURCE_NAME = "ares"
PAGE_SIZE = 100            # počet záznamů na stránku (bezpečně pod stropem)
MAX_RESULTS = 1000        # tvrdý strop ARES na celkový počet shod
TOO_MANY = "VYSTUP_PRILIS_MNOHO_VYSLEDKU"


class AresError(Exception):
    """Logická chyba vrácená ARES API (např. překročení stropu 1000)."""

    def __init__(self, message: str, sub_kod: str | None = None):
        super().__init__(message)
        self.sub_kod = sub_kod


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize(subj: dict[str, Any], nace_label: str | None = None) -> Optional[Lead]:
    """Převede surový ARES subjekt na `Lead`. Vrátí None, když chybí IČO."""
    ico = subj.get("ico")
    if not ico:
        return None
    sidlo = subj.get("sidlo") or {}
    return Lead(
        source=SOURCE_NAME,
        external_id=str(ico),
        name=subj.get("obchodniJmeno") or "(bez názvu)",
        nace=list(subj.get("czNace") or []),
        obor=nace_label,
        region=sidlo.get("nazevKraje"),
        url=DETAIL_URL.format(ico=ico),
        date=_parse_date(subj.get("datumVzniku")),
        raw=subj,
    )


class AresClient:
    """Tenký HTTP klient nad ARES REST API."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 30.0):
        self._client = client or httpx.Client(
            timeout=timeout, headers={"accept": "application/json"}
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "AresClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """Pošle dotaz s jednoduchým retry na přechodné chyby. Vrátí JSON
        (úspěch i logickou chybu ARES); transportní/5xx chyby vyhodí AresError."""
        last_exc: Exception | None = None
        for _ in range(3):
            try:
                resp = self._client.post(ARES_BASE + SEARCH_PATH, json=body)
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = AresError(f"HTTP {resp.status_code}")
                continue
            try:
                return resp.json()
            except ValueError as exc:
                last_exc = exc
                continue
        raise AresError(f"ARES request failed: {last_exc}")

    def search_segment(
        self, address_filter: dict[str, Any], nace_code: str, page_size: int = PAGE_SIZE
    ) -> list[dict[str, Any]]:
        """Stáhne VŠECHNY záznamy pro jeden segment (adresa × NACE).

        Vyhodí `AresError` (sub_kod=VYSTUP_PRILIS_MNOHO_VYSLEDKU), pokud segment
        překračuje strop 1000 a je třeba ho zúžit (např. přes městskou část).
        """
        results: list[dict[str, Any]] = []
        start = 0
        while True:
            body = {
                "sidlo": address_filter,
                "czNace": [nace_code],
                "start": start,
                "pocet": page_size,
            }
            data = self._post(body)
            if "ekonomickeSubjekty" not in data:
                raise AresError(
                    f"{data.get('kod')}/{data.get('subKod')}: {data.get('popis', '')}",
                    sub_kod=data.get("subKod"),
                )
            batch = data.get("ekonomickeSubjekty") or []
            results.extend(batch)
            total = data.get("pocetCelkem", len(results))
            start += page_size
            if not batch or start >= total or start >= MAX_RESULTS:
                break
        return results


class AresSource(Source):
    """Zdroj leadů z ARES dle `Targets`."""

    name = SOURCE_NAME

    def __init__(
        self,
        targets: Targets,
        client: AresClient | None = None,
        today: date | None = None,
    ):
        self.targets = targets
        self.client = client or AresClient()
        self.today = today or date.today()

    def close(self) -> None:
        self.client.close()

    def _fetch_segment(self, loc: Locality, nace_code: str, nace_label: str) -> list[dict[str, Any]]:
        """Stáhne raw záznamy pro lokalitu × NACE. Při přetečení stropu 1000 automaticky
        zúží na nakonfigurované městské části (`loc.mestske_casti`)."""
        try:
            return self.client.search_segment(loc.filter, nace_code)
        except AresError as exc:
            if exc.sub_kod != TOO_MANY:
                logger.warning("Segment %s × %s selhal: %s", loc.name, nace_code, exc)
                return []
            if not loc.mestske_casti:
                logger.warning(
                    "Segment %s × %s (%s) překračuje strop 1000 záznamů ARES a nemá "
                    "nakonfigurované městské části — přeskakuji.", loc.name, nace_code, nace_label,
                )
                return []

        # Zúžení na městské části.
        logger.info(
            "Segment %s × %s přeteklo strop — zužuji na %d městských částí.",
            loc.name, nace_code, len(loc.mestske_casti),
        )
        out: list[dict[str, Any]] = []
        for mc in loc.mestske_casti:
            try:
                out.extend(self.client.search_segment({"kodMestskeCastiObvodu": mc}, nace_code))
            except AresError as exc:
                if exc.sub_kod == TOO_MANY:
                    logger.warning(
                        "Městská část %s × %s stále přes strop 1000 — vyžaduje jemnější "
                        "dělení (kodCastiObce). Přeskakuji.", mc, nace_code,
                    )
                else:
                    logger.warning("Městská část %s × %s selhala: %s", mc, nace_code, exc)
        return out

    def fetch(self) -> list[Lead]:
        cutoff = self.today - timedelta(days=self.targets.max_age_days)
        kraj_codes = set(self.targets.kraj_codes)
        seen_ico: set[str] = set()
        leads: list[Lead] = []

        for loc in self.targets.localities:
            for nace in self.targets.nace:
                raw = self._fetch_segment(loc, nace.code, nace.label)
                for subj in raw:
                    if kraj_codes:
                        kod_kraje = (subj.get("sidlo") or {}).get("kodKraje")
                        if kod_kraje not in kraj_codes:
                            continue
                    lead = normalize(subj, nace_label=nace.label)
                    if lead is None or lead.date is None or lead.date < cutoff:
                        continue
                    if lead.external_id in seen_ico:
                        continue
                    seen_ico.add(lead.external_id)
                    leads.append(lead)

        leads.sort(key=lambda l: (l.date or date.min), reverse=True)
        return leads
