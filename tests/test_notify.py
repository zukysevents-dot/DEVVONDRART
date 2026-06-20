"""Testy notifikace — výběr pro digest, render šablony, sestavení a odeslání e-mailu."""
from __future__ import annotations

from datetime import date

import pytest

from src.config import Settings
from src.models import Lead
from src.notify import (
    NotifyError,
    build_message,
    build_subject,
    build_summary,
    render_digest,
    select_for_digest,
    send_digest,
)


def lead(ico: str, score, name: str = "Firma") -> Lead:
    return Lead(
        source="ares", external_id=ico, name=name, obor="Bary a kavárny",
        nace=["56300"], region="Jihomoravský kraj", date=date(2026, 5, 20),
        url=f"https://ares.gov.cz/ekonomicke-subjekty?ico={ico}",
        score=score, reason="důvod" if score else None,
        outreach_draft="Dobrý den" if score else None,
    )


# --- select_for_digest -----------------------------------------------------

def test_select_filters_below_threshold_keeps_unscored_and_sorts():
    leads = [lead("1", 8), lead("2", 3), lead("3", None)]
    out = select_for_digest(leads, threshold=5)
    assert [l.external_id for l in out] == ["1", "3"]  # 8 nahoře, neoskórovaný dole, skóre 3 pryč


# --- render_digest ---------------------------------------------------------

def test_render_contains_key_fields():
    leads = [lead("29579074", 9, name="Fugazi s.r.o.")]
    summary = build_summary(date(2026, 6, 20), leads, leads, threshold=5)
    html = render_digest(leads, summary)
    assert "Fugazi s.r.o." in html
    assert "9/10" in html
    assert "důvod" in html
    assert "Dobrý den" in html
    assert "ico=29579074" in html
    assert "nad prahem" in html


def test_render_empty():
    summary = build_summary(date(2026, 6, 20), [], [], threshold=5)
    html = render_digest([], summary)
    assert "žádné nové leady" in html.lower()


# --- e-mail ----------------------------------------------------------------

def _settings(**kw) -> Settings:
    base = dict(
        smtp_host="smtp.test", smtp_port=587, smtp_user="bot@test",
        smtp_password="secret", digest_from="bot@test", digest_to="me@test",
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_build_message_has_html_alternative():
    msg = build_message("<p>ahoj</p>", "Předmět", _settings())
    assert msg["To"] == "me@test"
    assert msg["From"] == "bot@test"
    assert "text/html" in [part.get_content_type() for part in msg.walk()]


def test_build_message_requires_recipient():
    with pytest.raises(NotifyError):
        build_message("<p>x</p>", "S", _settings(digest_to=None))


class FakeSMTP:
    def __init__(self):
        self.sent = []
        self.quit_called = False

    def send_message(self, msg):
        self.sent.append(msg)

    def quit(self):
        self.quit_called = True


def test_send_digest_uses_smtp_factory():
    fake = FakeSMTP()
    send_digest("<p>hi</p>", "Subj", _settings(), smtp_factory=lambda s: fake)
    assert len(fake.sent) == 1
    assert fake.sent[0]["Subject"] == "Subj"
    assert fake.quit_called


def test_send_digest_without_host_raises():
    with pytest.raises(NotifyError):
        send_digest("<p>x</p>", "S", _settings(smtp_host=None), smtp_factory=lambda s: FakeSMTP())


def test_build_subject():
    summary = build_summary(date(2026, 6, 20), [lead("1", 8)], [lead("1", 8)], threshold=5)
    assert build_subject(summary) == "vondrart leady 2026-06-20: 1 nových"
