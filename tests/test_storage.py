"""Testy stavu/deduplikace (SeenStore)."""
from __future__ import annotations

from datetime import date

from src.models import Lead
from src.storage import SeenStore


def lead(ico: str, d: str, name: str = "Firma", source: str = "ares") -> Lead:
    return Lead(source=source, external_id=ico, name=name, date=date.fromisoformat(d))


def test_cold_start_and_sorting(tmp_path):
    store = SeenStore(tmp_path / "seen.json")
    assert store.is_cold_start
    sel = store.select_new([lead("2", "2026-06-01"), lead("1", "2026-06-10")])
    assert sel.cold_start
    assert [l.external_id for l in sel.new] == ["1", "2"]  # seřazeno dle data sestupně
    assert sel.skipped == 0


def test_dedup_persists_across_runs(tmp_path):
    path = tmp_path / "seen.json"
    leads = [lead("1", "2026-06-10"), lead("2", "2026-06-01")]

    s1 = SeenStore(path)
    s1.mark_seen(s1.select_new(leads).new, date(2026, 6, 20))
    s1.save(date(2026, 6, 20))

    s2 = SeenStore(path)
    assert not s2.is_cold_start
    assert s2.seen_count == 2
    sel = s2.select_new(leads + [lead("3", "2026-06-15")])
    assert [l.external_id for l in sel.new] == ["3"]


def test_cap_marks_overflow_as_seen(tmp_path):
    path = tmp_path / "seen.json"
    leads = [lead(str(i), f"2026-06-{i + 1:02d}") for i in range(5)]

    s1 = SeenStore(path)
    sel = s1.select_new(leads, max_new=2)
    assert len(sel.to_notify) == 2
    assert sel.skipped == 3
    assert len(sel.new) == 5  # všech 5 je "nových"
    s1.mark_seen(sel.new, date(2026, 6, 20))  # i oříznuté se označí jako viděné
    s1.save()

    s2 = SeenStore(path)
    assert s2.seen_count == 5
    assert s2.select_new(leads, max_new=2).new == []  # další běh už nic nového


def test_corrupt_file_resets_to_empty(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{ rozbity json", encoding="utf-8")
    store = SeenStore(path)
    assert store.is_cold_start
    assert store.seen_count == 0
