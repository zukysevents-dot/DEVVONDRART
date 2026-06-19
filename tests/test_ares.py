"""Testy ARES klienta — normalizace, filtrování (datum/kraj), dedup, strop 1000.

Bez sítě: httpx.MockTransport vrací nasimulované odpovědi ARES.
"""
from __future__ import annotations

import json
from datetime import date

import httpx

from src.config import Locality, NaceItem, Targets
from src.sources.ares import AresClient, AresSource, normalize


def make_subject(ico: str, name: str, datum: str, kraj: int = 116, nace: str = "56300") -> dict:
    return {
        "ico": ico,
        "obchodniJmeno": name,
        "datumVzniku": datum,
        "czNace": [nace],
        "sidlo": {
            "nazevKraje": "Jihomoravský kraj",
            "kodKraje": kraj,
            "nazevObce": "Brno",
        },
    }


def make_transport(subjects_by_nace: dict[str, list[dict]], too_many_nace: str | None = None):
    """Jedna stránka na segment; pro `too_many_nace` vrátí chybu stropu 1000."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        nace = body["czNace"][0]
        if too_many_nace and nace == too_many_nace:
            return httpx.Response(
                400,
                json={"kod": "CHYBA_VSTUPU", "subKod": "VYSTUP_PRILIS_MNOHO_VYSLEDKU", "popis": "moc"},
            )
        subs = subjects_by_nace.get(nace, [])
        page = subs if body.get("start", 0) == 0 else []
        return httpx.Response(200, json={"pocetCelkem": len(subs), "ekonomickeSubjekty": page})

    return httpx.MockTransport(handler)


def test_normalize_maps_fields():
    lead = normalize(make_subject("123", "ACME", "2026-01-02"), nace_label="Test")
    assert lead is not None
    assert lead.source == "ares"
    assert lead.external_id == "123"
    assert lead.name == "ACME"
    assert lead.obor == "Test"
    assert lead.region == "Jihomoravský kraj"
    assert lead.url.endswith("ico=123")
    assert lead.date == date(2026, 1, 2)


def test_normalize_without_ico_returns_none():
    assert normalize({"obchodniJmeno": "bez IČO"}) is None


def test_fetch_filters_dedups_and_skips_overcap():
    today = date(2026, 6, 20)
    subs = {
        "56300": [
            make_subject("111", "Nová kavárna", "2026-06-10"),        # čerstvá, JMK -> ponechat
            make_subject("111", "Duplikát", "2026-06-10"),            # stejné IČO -> zahodit
            make_subject("222", "Stará firma", "2024-01-01"),         # mimo 30 dní -> zahodit
            make_subject("333", "Praha s.r.o.", "2026-06-12", kraj=27),  # jiný kraj -> zahodit
        ]
    }
    transport = make_transport(subs, too_many_nace="56110")
    client = AresClient(client=httpx.Client(transport=transport))
    targets = Targets(
        kraj_codes=[116],
        max_age_days=30,
        localities=[Locality(name="Brno", filter={"kodObce": 582786})],
        nace=[
            NaceItem(code="56300", label="Bary a kavárny"),
            NaceItem(code="56110", label="Restaurace"),  # přeteče strop -> přeskočit, ne spadnout
        ],
    )
    leads = AresSource(targets, client=client, today=today).fetch()

    assert [l.external_id for l in leads] == ["111"]
    assert leads[0].name == "Nová kavárna"
    assert leads[0].obor == "Bary a kavárny"


def test_fetch_subdivides_into_mestske_casti_on_overcap():
    today = date(2026, 6, 20)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sidlo = body["sidlo"]
        if "kodObce" in sidlo:  # základní dotaz za celé Brno -> přes strop
            return httpx.Response(
                400,
                json={"kod": "CHYBA_VSTUPU", "subKod": "VYSTUP_PRILIS_MNOHO_VYSLEDKU", "popis": "moc"},
            )
        subs = (
            [make_subject("777", "Kavárna Střed", "2026-06-18", nace="56110")]
            if sidlo.get("kodMestskeCastiObvodu") == 550973
            else []
        )
        page = subs if body.get("start", 0) == 0 else []
        return httpx.Response(200, json={"pocetCelkem": len(subs), "ekonomickeSubjekty": page})

    client = AresClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    targets = Targets(
        kraj_codes=[116],
        max_age_days=30,
        localities=[
            Locality(name="Brno", filter={"kodObce": 582786}, mestske_casti=[550973, 551007])
        ],
        nace=[NaceItem(code="56110", label="Restaurace")],
    )
    leads = AresSource(targets, client=client, today=today).fetch()
    assert [l.external_id for l in leads] == ["777"]
    assert leads[0].name == "Kavárna Střed"


def test_fetch_without_kraj_filter_keeps_all_recent():
    today = date(2026, 6, 20)
    subs = {"56300": [make_subject("999", "Mimo JMK", "2026-06-15", kraj=27)]}
    client = AresClient(client=httpx.Client(transport=make_transport(subs)))
    targets = Targets(
        kraj_codes=[],  # bez kontroly kraje
        max_age_days=30,
        localities=[Locality(name="X", filter={"kodObce": 1})],
        nace=[NaceItem(code="56300", label="Bary")],
    )
    leads = AresSource(targets, client=client, today=today).fetch()
    assert [l.external_id for l in leads] == ["999"]
