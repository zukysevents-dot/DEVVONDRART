"""Orchestrace pipeline.

Hotové milníky:
  M1 — sběr nových firem z ARES
  M2 — deduplikace proti data/seen.json + cold start
  M3 — scoring přes Claude API
  M4 — HTML e-mailový digest přes SMTP

Spuštění:
    python main.py
"""
from __future__ import annotations

import logging
from datetime import date

from src.config import Settings, load_profile, load_targets, resolve_path
from src.notify import (
    build_subject,
    build_summary,
    render_digest,
    select_for_digest,
    send_digest,
)
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

    # M4 — sestavení digestu (řazeno dle skóre, odfiltrování pod prahem)
    digest_leads = select_for_digest(selection.to_notify, targets.score_threshold)
    summary = build_summary(today, selection.to_notify, digest_leads, targets.score_threshold)
    html = render_digest(digest_leads, summary)
    subject = build_subject(summary)
    print(f"Digest: {summary.shown} k zobrazení (nad prahem {summary.above_threshold}, práh {summary.threshold}).")

    # Odeslání přes SMTP, nebo náhled do souboru když SMTP není nastaveno.
    delivered = False
    if settings.smtp_host and settings.digest_to:
        try:
            send_digest(html, subject, settings)
            print(f"Digest odeslán na {settings.digest_to}: {subject}")
            delivered = True
        except Exception as exc:  # neúspěch nesmí ztratit leady
            logger.error("Odeslání digestu selhalo (%s) — stav neukládám, zkusí se příště.", exc)
    else:
        preview = resolve_path("data/digest_preview.html")
        preview.write_text(html, encoding="utf-8")
        logger.warning(
            "SMTP/adresát nenastaven — digest neodeslán (náhledový režim). Náhled: %s", preview
        )

    # Stav uložíme jen po skutečném odeslání (jinak se leady zkusí příště).
    if delivered:
        store.mark_seen(selection.new, today)
        store.save(today)
        print(f"Stav uložen: celkem viděno {store.seen_count} firem ({store.path}).")
    else:
        logger.info("Stav neuložen (digest neodeslán / náhledový režim).")


if __name__ == "__main__":
    main()
