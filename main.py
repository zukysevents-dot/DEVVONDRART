"""Orchestrace pipeline.

Hotové milníky:
  M1 — sběr nových firem z ARES
  M2 — deduplikace proti data/seen.json + cold start

Spuštění:
    python main.py
"""
from __future__ import annotations

import logging
from datetime import date

from src.config import Settings, load_targets, resolve_path
from src.sources.ares import AresSource
from src.storage import SeenStore


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    setup_logging()
    today = date.today()
    settings = Settings()
    targets = load_targets(settings)

    print("== vondrart lead-finder ==")
    print(f"Lokality: {', '.join(loc.name for loc in targets.localities)}")
    print(f"NACE: {', '.join(n.code for n in targets.nace)}")
    print(f"Stáří firem: posledních {targets.max_age_days} dní")
    print(f"Kontrola kraje (kodKraje): {targets.kraj_codes or 'vypnuto'}\n")

    # M1 — sběr
    source = AresSource(targets, today=today)
    try:
        leads = source.fetch()
    finally:
        source.client.close()

    # M2 — dedup proti uloženému stavu
    store = SeenStore(resolve_path(settings.seen_path))
    selection = store.select_new(leads, targets.max_new_per_run)

    if selection.cold_start:
        print("(první běh — cold start; stav byl prázdný)\n")
    print(
        f"Ve výběrovém okně: {len(leads)} firem | "
        f"nových (nevidělných): {len(selection.new)} | "
        f"k zobrazení: {len(selection.to_notify)} | "
        f"oříznuto limitem: {selection.skipped}\n"
    )

    # (M3 doplní scoring na selection.to_notify, M4 e-mailový digest.)
    for lead in selection.to_notify:
        print(f"[{lead.date}] {lead.name}  (IČO {lead.external_id})")
        print(f"    obor: {lead.obor or '-'} | NACE {', '.join(lead.nace) or '-'} | {lead.region or '-'}")
        print(f"    {lead.url}")

    # Stav se zapisuje až po zpracování běhu (v dalších milnících až po odeslání digestu).
    store.mark_seen(selection.new, today)
    store.save(today)
    print(f"\nStav uložen: celkem viděno {store.seen_count} firem ({store.path}).")


if __name__ == "__main__":
    main()
