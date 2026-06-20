"""Testy scoringu — parsování JSON, clamp, retry/backoff, vzdání se. Bez sítě/klíče."""
from __future__ import annotations

from datetime import date

import pytest

from src.models import Lead
from src.scoring import RetryableError, Score, Scorer, parse_score


def a_lead() -> Lead:
    return Lead(source="ares", external_id="1", name="Nová kavárna", date=date(2026, 6, 1))


# --- parse_score -----------------------------------------------------------

def test_parse_clean_json():
    s = parse_score('{"score": 8, "reason": "sedí", "outreach_draft": "Dobrý den"}')
    assert s == Score(8, "sedí", "Dobrý den")


def test_parse_with_fences_and_prose():
    raw = 'Tady je výsledek:\n```json\n{"score": 7, "reason": "fajn", "outreach_draft": "Ahoj"}\n```'
    s = parse_score(raw)
    assert s is not None and s.score == 7


def test_parse_clamps_out_of_range():
    assert parse_score('{"score": 15, "reason": "x", "outreach_draft": "y"}').score == 10
    assert parse_score('{"score": 0, "reason": "x", "outreach_draft": "y"}').score == 1


@pytest.mark.parametrize("raw", ["", "není tu json", '{"reason": "chybí score"}', "{rozbité}"])
def test_parse_invalid_returns_none(raw):
    assert parse_score(raw) is None


# --- Scorer ----------------------------------------------------------------

def make_scorer(responses, **kw):
    """complete_fn vrací postupně prvky `responses`; položka typu Exception se vyhodí."""
    calls = {"n": 0}

    def complete(system, user):
        item = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    scorer = Scorer("PROFIL", complete, sleep=lambda _s: None, **kw)
    return scorer, calls


def test_score_lead_success():
    scorer, calls = make_scorer(['{"score": 9, "reason": "r", "outreach_draft": "o"}'])
    s = scorer.score_lead(a_lead())
    assert s.score == 9 and calls["n"] == 1


def test_retry_on_transient_then_success():
    scorer, calls = make_scorer([
        RetryableError("rate limit"),
        '{"score": 6, "reason": "r", "outreach_draft": "o"}',
    ])
    s = scorer.score_lead(a_lead())
    assert s.score == 6 and calls["n"] == 2


def test_retry_on_bad_json_then_success():
    scorer, calls = make_scorer(['nonsense', '{"score": 5, "reason": "r", "outreach_draft": "o"}'])
    s = scorer.score_lead(a_lead())
    assert s.score == 5 and calls["n"] == 2


def test_gives_up_after_max_retries():
    scorer, calls = make_scorer(['nonsense'], max_retries=3)
    assert scorer.score_lead(a_lead()) is None
    assert calls["n"] == 3


def test_score_leads_attaches_fields():
    scorer, _ = make_scorer(['{"score": 8, "reason": "sedí", "outreach_draft": "Dobrý den"}'])
    leads = scorer.score_leads([a_lead()])
    assert leads[0].score == 8
    assert leads[0].reason == "sedí"
    assert leads[0].outreach_draft == "Dobrý den"
