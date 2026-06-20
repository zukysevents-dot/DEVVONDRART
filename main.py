"""Orchestrace pipeline.

Hotové milníky:
  M1 — sběr nových firem z ARES
  M2 — deduplikace proti data/seen.json + cold start
  M3 — scoring přes Claude API

Spuštění:
    python main.py
"""
from __future__ import annotations

import logging
from datetime import date

from src.config import Settings, load_profile, load_targets, resolve_path
from src.scoring import Scorer
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

    # M3 — scoring přes Claude API (pokud je klíč; jinak se přeskočí)
    if selection.to_notify and settings.anthropic_api_key:
        scorer = Scorer.from_settings(settings, load_profile(settings))
        scorer.score_leads(selection.to_notify)
        selection.to_notify.sort(key=lambda l: (l.score or 0), reverse=True)
    elif selection.to_notify:
        logger.warning("ANTHROPIC_API_KEY není nastaven — scoring přeskočen (leady bez skóre).")

    # (M4 doplní e-mailový digest; práh skóre targets.score_threshold.)
    for lead in selection.to_notify:
        score = f"skóre {lead.score}/10" if lead.score is not None else "bez skóre"
        print(f"[{lead.date}] {lead.name}  (IČO {lead.external_id}) — {score}")
        print(f"    obor: {lead.obor or '-'} | NACE {', '.join(lead.nace) or '-'} | {lead.region or '-'}")
        if lead.reason:
            print(f"    proč: {lead.reason}")
        if lead.outreach_draft:
            print(f"    návrh oslovení: {lead.outreach_draft}")
        print(f"    {lead.url}")

    # Stav se zapisuje až po zpracování běhu (v dalších milnících až po odeslání digestu).
    store.mark_seen(selection.new, today)
    store.save(today)
    print(f"\nStav uložen: celkem viděno {store.seen_count} firem ({store.path}).")


if __name__ == "__main__":
    main()
