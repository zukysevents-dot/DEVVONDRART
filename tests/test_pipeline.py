"""End-to-end test celé pipeline (main.run) se vstřikovanými fake závislostmi.

Pokrývá: sběr -> dedup -> scoring -> sestavení a odeslání digestu -> uložení stavu,
a deduplikaci při druhém běhu (stav načtený z disku).
"""
from __future__ import annotations

import types
from datetime import date

import main as app
from src.config import Locality, NaceItem, Settings, Targets
from src.models import Lead
from src.scoring import Scorer
from src.storage import SeenStore


class FakeSource:
    name = "ares"

    def __init__(self, leads: list[Lead]):
        self._leads = leads
        self.client = types.SimpleNamespace(close=lambda: None)

    def fetch(self) -> list[Lead]:
        return [l.model_copy() for l in self._leads]


class FakeSMTP:
    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(msg)

    def quit(self):
        pass


def stub_complete(system: str, user: str) -> str:
    return '{"score": 9, "reason": "sedí na profil", "outreach_draft": "Dobrý den"}'


def _settings(**kw) -> Settings:
    base = dict(
        smtp_host="smtp.test", smtp_port=587, smtp_user="bot@test",
        smtp_password="x", digest_from="bot@test", digest_to="me@test",
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


def _targets() -> Targets:
    return Targets(
        kraj_codes=[], max_age_days=60, max_new_per_run=100, score_threshold=5,
        localities=[Locality(name="Brno", filter={"kodObce": 1})],
        nace=[NaceItem(code="56300", label="Bary a kavárny")],
    )


def _html_part(msg) -> str:
    part = [p for p in msg.walk() if p.get_content_type() == "text/html"][0]
    return part.get_content()


def test_pipeline_sends_digest_and_persists_then_dedups(tmp_path):
    leads = [
        Lead(source="ares", external_id="1", name="Nová kavárna", obor="Bary a kavárny",
             nace=["56300"], region="Jihomoravský kraj", date=date(2026, 5, 20)),
    ]
    seen = tmp_path / "seen.json"
    sent_boxes = []

    def smtp_factory(_settings):
        box = FakeSMTP()
        sent_boxes.append(box)
        return box

    # 1. běh: odešle digest, oskóruje, uloží stav
    report = app.run(
        _settings(), _targets(), today=date(2026, 6, 20),
        source=FakeSource(leads), store=SeenStore(seen),
        scorer=Scorer("PROFIL", stub_complete, sleep=lambda _s: None),
        smtp_factory=smtp_factory,
    )
    assert report.delivered is True
    assert report.cold_start is True
    assert report.digest_shown == 1
    assert len(sent_boxes) == 1 and len(sent_boxes[0].sent) == 1
    assert "Nová kavárna" in _html_part(sent_boxes[0].sent[0])
    assert "9/10" in _html_part(sent_boxes[0].sent[0])
    assert seen.exists()

    # 2. běh: stav z disku -> nic nového, nic se neodesílá
    report2 = app.run(
        _settings(), _targets(), today=date(2026, 6, 20),
        source=FakeSource(leads), store=SeenStore(seen),
        scorer=Scorer("PROFIL", stub_complete, sleep=lambda _s: None),
        smtp_factory=smtp_factory,
    )
    assert report2.new_count == 0
    assert report2.digest_shown == 0


def test_pipeline_failed_send_does_not_persist(tmp_path):
    leads = [Lead(source="ares", external_id="9", name="Bistro", obor="Bary a kavárny",
                  nace=["56300"], region="Jihomoravský kraj", date=date(2026, 5, 20))]
    seen = tmp_path / "seen.json"

    def boom(_settings):
        raise RuntimeError("SMTP down")

    report = app.run(
        _settings(), _targets(), today=date(2026, 6, 20),
        source=FakeSource(leads), store=SeenStore(seen),
        scorer=Scorer("PROFIL", stub_complete, sleep=lambda _s: None),
        smtp_factory=boom,
    )
    assert report.delivered is False
    assert not seen.exists()  # stav se neuloží -> lead se zkusí příště
