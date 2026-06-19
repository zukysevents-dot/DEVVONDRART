"""Orchestrace pipeline. Milník 1: stáhne nové firmy z ARES a vypíše je do konzole.

Spuštění:
    python main.py
"""
from __future__ import annotations

import logging

from src.config import Settings, load_targets
from src.sources.ares import AresSource


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    setup_logging()
    settings = Settings()
    targets = load_targets(settings)

    print("== vondrart lead-finder — Milník 1 (ARES) ==")
    print(f"Lokality: {', '.join(loc.name for loc in targets.localities)}")
    print(f"NACE: {', '.join(n.code for n in targets.nace)}")
    print(f"Stáří firem: posledních {targets.max_age_days} dní")
    print(f"Kontrola kraje (kodKraje): {targets.kraj_codes or 'vypnuto'}\n")

    source = AresSource(targets)
    try:
        leads = source.fetch()
    finally:
        source.client.close()

    print(f"Nalezeno {len(leads)} nových firem:\n")
    for lead in leads[:20]:
        print(f"[{lead.date}] {lead.name}  (IČO {lead.external_id})")
        print(f"    obor: {lead.obor or '-'} | NACE {', '.join(lead.nace) or '-'} | {lead.region or '-'}")
        print(f"    {lead.url}")
    if len(leads) > 20:
        print(f"\n... a dalších {len(leads) - 20}.")


if __name__ == "__main__":
    main()
