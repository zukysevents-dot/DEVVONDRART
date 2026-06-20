"""Testy Webtrh zdroje — parsování výpisu, relativní datum, fetch (mock, bez sítě)."""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from src.sources.webtrh import WebtrhSource, parse_listing, parse_relative_date

TODAY = date(2026, 6, 20)

FIXTURE = """
<div class="box">
  <div class="inquiry-box unread ">
    <a href="https://webtrh.cz/poptavka/hledam-grafika-pro-logo/">
      <div class="title"><span>Hledám grafika pro logo</span></div>
      <div class="meta">
        <div>Rozpočet: <b>10 - 25 tisíc Kč</b></div>
        <div>Kategorie: <b>Grafika</b></div>
      </div>
    </a>
    <div class="created">před 2 dny</div>
  </div>
  <hr>
  <div class="inquiry-box unread ">
    <a href="https://webtrh.cz/poptavka/branding-pro-novou-kavarnu/">
      <div class="title"><span>Branding pro novou kavárnu</span></div>
      <div class="meta">
        <div>Kategorie: <b>Branding</b></div>
      </div>
    </a>
    <div class="created">dnes</div>
  </div>
  <div class="inquiry-box unread ">
    <a href="https://webtrh.cz/poptavka/stare-poptavka/">
      <div class="title"><span>Stará poptávka</span></div>
      <div class="meta"><div>Kategorie: <b>Web</b></div></div>
    </a>
    <div class="created">před 100 dny</div>
  </div>
</div>
"""


# --- parse_relative_date ---------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("dnes", TODAY),
    ("před chvílí", TODAY),
    ("před 3 hodinami", TODAY),
    ("včera", date(2026, 6, 19)),
    ("před 2 dny", date(2026, 6, 18)),
    ("před 1 dnem", date(2026, 6, 19)),
    ("před 3 týdny", date(2026, 5, 30)),
    ("", None),
    ("nesmysl", None),
])
def test_parse_relative_date(text, expected):
    assert parse_relative_date(text, TODAY) == expected


# --- parse_listing ---------------------------------------------------------

def test_parse_listing_extracts_fields():
    leads = parse_listing(FIXTURE, today=TODAY)
    assert len(leads) == 3
    first = leads[0]
    assert first.source == "webtrh"
    assert first.external_id == "hledam-grafika-pro-logo"
    assert first.name == "Hledám grafika pro logo"
    assert first.obor == "Grafika"
    assert first.region is None
    assert first.url == "https://webtrh.cz/poptavka/hledam-grafika-pro-logo/"
    assert first.date == date(2026, 6, 18)
    assert first.raw["rozpocet"] == "10 - 25 tisíc Kč"
    assert leads[1].date == TODAY  # "dnes"


# --- WebtrhSource.fetch ----------------------------------------------------

def make_source(html: str, **kw) -> WebtrhSource:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=html))
    return WebtrhSource(client=httpx.Client(transport=transport), today=TODAY, **kw)


def test_fetch_returns_all_without_age_filter():
    leads = make_source(FIXTURE).fetch()
    assert {l.external_id for l in leads} == {
        "hledam-grafika-pro-logo", "branding-pro-novou-kavarnu", "stare-poptavka",
    }


def test_fetch_applies_max_age_filter():
    leads = make_source(FIXTURE, max_age_days=30).fetch()
    ids = {l.external_id for l in leads}
    assert "stare-poptavka" not in ids  # 100 dní > 30
    assert "hledam-grafika-pro-logo" in ids


def test_fetch_handles_http_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    src = WebtrhSource(client=httpx.Client(transport=transport), today=TODAY)
    assert src.fetch() == []  # nedostupnost zdroj jen přeskočí
