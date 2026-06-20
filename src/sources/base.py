"""Jednotné rozhraní zdroje leadů.

Každý zdroj (ARES, později Webtrh, …) je modul v `src/sources/` implementující
`Source.fetch()`, který vrací list normalizovaných `Lead` objektů. Díky tomu je
přidání dalšího zdroje triviální (pipeline dedup -> scoring -> digest je společná).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.models import Lead


class Source(ABC):
    name: str = "source"

    @abstractmethod
    def fetch(self) -> list[Lead]:
        """Stáhne a vrátí normalizované leady z tohoto zdroje."""
        raise NotImplementedError

    def close(self) -> None:
        """Uvolní případné zdroje (HTTP klient). Výchozí implementace nic nedělá."""
