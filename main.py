"""Orchestrace celé pipeline.

    ARES (sběr) -> dedup (seen.json) -> scoring (Claude) -> digest (e-mail/SMTP)

Logika běhu je v `run()` se vstřikovatelnými závislostmi (zdroj, stav, scorer, SMTP),
takže celá pipeline jde otestovat bez sítě. `main()` jen sestaví reálné komponenty
z konfigurace a běh spustí.

Spuštění:
    python main.py
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from src.config import Settings, Targets, load_profile, load_targets, resolve_path
from src.notify import (
    build_subject,
    build_summary,
    render_digest,
    select_for_digest,
    send_digest,
)
from src.scoring import Scorer
from src.sources.ares import AresSource
from src.sources.base import Source
from src.storage import SeenStore

logger = logging.getLogger(__name__)


@dataclass
class RunReport:
    cold_start: bool
    window_count: int       # firem ve výběrovém okně
    new_count: int          # dosud neviděných
    skipped: int            # oříznuto limitem na běh
    digest_shown: int       # v digestu (po prahu)
    above_threshold: int    # se skóre nad prahem
    delivered: bool         # digest odeslán e-mailem
    preview_path: Optional[Path]  # cesta k náhledu (náhledový režim)
    subject: str


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def run(
    settings: Settings,
    targets: Targets,
    *,
    today: date,
    source: Source | None = None,
    store: SeenStore | None = None,
    scorer: Scorer | None = None,
    smtp_factory: Optional[Callable] = None,
) -> RunReport:
    """Projede celou pipeline a vrátí přehled běhu."""
    # 1) Sběr leadů ze zdroje.
    created_source = source is None
    source = source or AresSource(targets, today=today)
    try:
        leads = source.fetch()
    finally:
        if created_source:
            source.client.close()  # type: ignore[attr-defined]

    # 2) Deduplikace proti uloženému stavu.
    store = store or SeenStore(resolve_path(settings.seen_path))
    selection = store.select_new(leads, targets.max_new_per_run)

    # 3) Scoring (vstřikovaný scorer; jinak z konfigurace, pokud je klíč).
    if scorer is None and settings.anthropic_api_key:
        scorer = Scorer.from_settings(settings, load_profile(settings))
    if scorer is not None and selection.to_notify:
        scorer.score_leads(selection.to_notify)
    elif selection.to_notify and not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY není nastaven — scoring přeskočen (leady bez skóre).")

    # 4) Sestavení digestu (řazeno dle skóre, odfiltrování pod prahem).
    digest_leads = select_for_digest(selection.to_notify, targets.score_threshold)
    summary = build_summary(today, selection.to_notify, digest_leads, targets.score_threshold)
    html = render_digest(digest_leads, summary)
    subject = build_subject(summary)

    # 5) Odeslání e-mailem, nebo náhled do souboru když SMTP není nastaveno.
    delivered = False
    preview_path: Path | None = None
    if settings.smtp_host and settings.digest_to:
        try:
            send_digest(html, subject, settings, smtp_factory=smtp_factory)
            delivered = True
        except Exception as exc:  # neúspěch nesmí ztratit leady
            logger.error("Odeslání digestu selhalo (%s) — stav neukládám, zkusí se příště.", exc)
    else:
        preview_path = resolve_path("data/digest_preview.html")
        preview_path.write_text(html, encoding="utf-8")
        logger.warning(
            "SMTP/adresát nenastaven — digest neodeslán (náhledový režim). Náhled: %s", preview_path
        )

    # 6) Stav uložíme jen po skutečném odeslání (jinak se leady zkusí příště).
    if delivered:
        store.mark_seen(selection.new, today)
        store.save(today)

    return RunReport(
        cold_start=selection.cold_start,
        window_count=len(leads),
        new_count=len(selection.new),
        skipped=selection.skipped,
        digest_shown=summary.shown,
        above_threshold=summary.above_threshold,
        delivered=delivered,
        preview_path=preview_path,
        subject=subject,
    )


def main() -> None:
    setup_logging()
    today = date.today()
    settings = Settings()
    targets = load_targets(settings)

    print("== vondrart lead-finder ==")
    print(f"Lokality: {', '.join(loc.name for loc in targets.localities)}")
    print(f"NACE: {', '.join(n.code for n in targets.nace)}")
    print(f"Stáří firem: posledních {targets.max_age_days} dní | práh skóre: {targets.score_threshold}\n")

    report = run(settings, targets, today=today)

    if report.cold_start:
        print("(první běh — cold start; stav byl prázdný)")
    print(
        f"Okno: {report.window_count} firem | nových: {report.new_count} | "
        f"k digestu: {report.digest_shown} (nad prahem {report.above_threshold}) | "
        f"oříznuto limitem: {report.skipped}"
    )
    if report.delivered:
        print(f"Digest odeslán: {report.subject}")
    elif report.preview_path:
        print(f"Náhled digestu uložen: {report.preview_path}")


if __name__ == "__main__":
    main()
