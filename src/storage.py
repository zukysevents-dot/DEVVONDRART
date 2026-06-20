"""Stav a deduplikace — `data/seen.json`.

Drží už zpracovaná `external_id` (klíč `source:external_id`), aby stejný lead
nechodil v digestu dokola. Ošetřuje cold start (první běh): když je nových leadů
nad limit `max_new_per_run`, zobrazí jen nejnovějších N a zbytek označí jako viděné
bez notifikace (aby první digest nebyl o stovkách položek).

GitHub Actions runner je ephemeral — v Milníku 6 se aktualizovaný soubor commitne
zpět do repa botem. Zápis je atomický (tmp + replace).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.models import Lead

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass
class SelectionResult:
    """Výsledek roztřídění leadů proti uloženému stavu."""

    new: list[Lead]          # všechny dosud neviděné leady (seřazené dle data sestupně)
    to_notify: list[Lead]    # podmnožina k notifikaci (po aplikaci limitu na běh)
    skipped: int             # kolik nových bylo nad limit (označí se jako viděné bez notifikace)
    cold_start: bool         # True, pokud byl stav prázdný (první běh)


class SeenStore:
    """Perzistentní stav viděných leadů v JSON souboru."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": SCHEMA_VERSION, "seen": {}, "meta": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("seen.json nelze načíst (%s) — začínám s prázdným stavem.", exc)
            return {"version": SCHEMA_VERSION, "seen": {}, "meta": {}}
        data.setdefault("seen", {})
        data.setdefault("meta", {})
        return data

    @staticmethod
    def key(lead: Lead) -> str:
        return f"{lead.source}:{lead.external_id}"

    @property
    def is_cold_start(self) -> bool:
        return not self._data.get("seen")

    @property
    def seen_count(self) -> int:
        return len(self._data["seen"])

    def is_seen(self, lead: Lead) -> bool:
        return self.key(lead) in self._data["seen"]

    def select_new(self, leads: list[Lead], max_new: int | None = None) -> SelectionResult:
        """Vybere dosud neviděné leady; při překročení `max_new` jich k notifikaci
        ponechá jen nejnovějších N (zbytek se pak označí jako viděné bez notifikace)."""
        cold = self.is_cold_start
        new = [lead for lead in leads if not self.is_seen(lead)]
        new.sort(key=lambda lead: (lead.date or date.min), reverse=True)

        if max_new and len(new) > max_new:
            to_notify = new[:max_new]
            skipped = len(new) - max_new
            logger.warning(
                "Nalezeno %d nových leadů, limit na běh je %d — zobrazím nejnovějších %d, "
                "%d starších označím jako viděné bez notifikace%s.",
                len(new), max_new, max_new, skipped, " (cold start)" if cold else "",
            )
        else:
            to_notify = new
            skipped = 0
        return SelectionResult(new=new, to_notify=to_notify, skipped=skipped, cold_start=cold)

    def mark_seen(self, leads: list[Lead], run_date: date) -> None:
        """Zapíše leady do stavu jako viděné (volat až po úspěšném zpracování běhu)."""
        for lead in leads:
            self._data["seen"][self.key(lead)] = {
                "first_seen": run_date.isoformat(),
                "name": lead.name,
                "date": lead.date.isoformat() if lead.date else None,
            }

    def save(self, run_date: date | None = None) -> None:
        """Atomicky uloží stav na disk."""
        self._data["version"] = SCHEMA_VERSION
        if run_date is not None:
            self._data["meta"]["last_run"] = run_date.isoformat()
        self._data["meta"]["seen_count"] = len(self._data["seen"])

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)
