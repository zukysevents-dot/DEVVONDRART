"""Datové modely sdílené napříč zdroji."""
from __future__ import annotations

import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class Lead(BaseModel):
    """Normalizovaný lead napříč všemi zdroji.

    Pole `score`, `reason` a `outreach_draft` doplní scoring (Milník 3).
    """

    source: str                                   # identifikátor zdroje, např. "ares"
    external_id: str                              # klíč pro deduplikaci; u ARES = IČO
    name: str                                     # obchodní jméno
    nace: list[str] = Field(default_factory=list) # CZ-NACE kódy (jak je vrací zdroj)
    obor: Optional[str] = None                    # lidský popisek oboru (z targets.yaml)
    region: Optional[str] = None                  # kraj (nazevKraje)
    url: Optional[str] = None                     # odkaz na detail (ARES/justice)
    date: Optional[datetime.date] = None          # datum vzniku / publikace
    raw: dict[str, Any] = Field(default_factory=dict)  # původní payload zdroje

    # --- doplní scoring (Milník 3) ---
    score: Optional[int] = None                   # 1–10
    reason: Optional[str] = None                  # jedna věta proč (ne)sedí
    outreach_draft: Optional[str] = None          # návrh prvního oslovení
