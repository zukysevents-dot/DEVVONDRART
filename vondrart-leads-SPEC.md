# Prompt pro Claude Code — „vondrart lead-finder"

> Tip: ulož tenhle soubor do prázdného repa jako `SPEC.md` a v Claude Code napiš:
> *„Přečti si SPEC.md a postav podle něj projekt. Začni Fází 1 (MVP) a po každém milníku se zastav, ať to můžu otestovat."*
> Nebo celý obsah níže vlož přímo jako první zprávu.

---

Jsi senior Python vývojář. Postav mi nástroj, který **každý den automaticky vyhledává potenciální zakázky (leady)** pro brandové studio a posílá mi je jako přehledný e-mailový digest s ohodnocením a návrhem oslovení. Stav to **iterativně po milnících** a po každém se zastav, ať to můžu otestovat.

## Kontext: pro koho to je

**vondrart studio** — brand & marketing studio z Brna. Dělají vizuální identity, loga, brand strategy, naming, tone of voice, packaging, social media a kampaně. Klientela jsou hlavně **nové a menší značky**: kavárny a bistra, lokální gastro, lifestyle a produktové značky, malé/rodinné firmy, e-shopy. Příklady z portfolia: lokální kavárna, café & bistro, lifestyle produktový brand, advokátní kancelář, rodinná firma na ploty, městská tour. Sweet spot = **firma, která se rozjíždí nebo rebranduje a potřebuje vizuální identitu**.

Tahle charakteristika je důležitá, protože ji nástroj použije při hodnocení relevance leadů. Ulož ji do `config/profile.md` jako editovatelný text — bude se vkládat do promptu pro hodnoticí model.

## Cíl a princip

Chci **outbound lead generation**: nečekat na poptávku, ale najít firmy, které branding budou brzy potřebovat — typicky **nově vzniklé firmy** v relevantních oborech a regionu. Pipeline:

1. **Sběr** nových záznamů ze zdrojů dat
2. **Deduplikace** proti už viděným (ať nechodí to samé dokola)
3. **Scoring přes Claude API** — fit 1–10 + jednou větou proč + návrh prvního oslovení
4. **Notifikace** — denní e-mailový digest (česky), seřazený podle skóre
5. **Plánování** — běží automaticky každý den

> Důležité: **samotný běh řídí scheduler (cron), ne MCP server.** Nestav žádný démon ani MCP. Je to plánovaná dávková úloha.

## Tech stack

- **Python 3.11+**
- HTTP: `httpx`
- LLM: oficiální `anthropic` SDK (model `claude-sonnet-4-6` na scoring; konfigurovatelné)
- Validace dat: `pydantic` v2
- E-mailová šablona: `jinja2`
- Konfigurace: `pydantic-settings` + `.env`, cílové obory/region v `config/targets.yaml`
- Plánovač: **GitHub Actions** (cron) — zdarma
- Žádná těžká databáze. Stav drž v `data/seen.json` (viz Stav níže)

Závislosti drž minimální. Použij `pyproject.toml` (klidně `uv`).

## DŮLEŽITÉ: nejdřív ověř externí API, nehádej

Než cokoli napíšeš proti ARES, **přečti si aktuální dokumentaci ARES API** (otevřená data Ministerstva financí, portál `ares.gov.cz`, je tam OpenAPI/Swagger) a podle ní napiš klienta. Nehardcoduj endpointy z paměti. Co o ARES vím a od čeho se odraz:

- Je to **oficiální, veřejné, zdarma, bez registrace**. Denní limity jsou vysoké (řádově desetitisíce dotazů).
- Vrací mj.: obchodní jméno, IČO, DIČ, adresu sídla (vč. kódu kraje/okresu), **datum vzniku**, právní formu a **CZ-NACE** (obor).
- Vyhledávací endpoint je pravděpodobně `POST .../ekonomicke-subjekty/vyhledat` s JSON filtrem — **ověř přesný tvar filtru, stránkování a rate limit v dokumentaci** a podle toho to napiš.
- Zjisti, jestli umí filtrovat přímo podle **data vzniku** (rozsah). Pokud ano, využij to. Pokud ne, použij fallback: dotaž segment (kraj + NACE), a „nové" detekuj diffem proti `seen.json` + kontrolou, že `datumVzniku` spadá do posledních N dní (konfigurovatelné, default 30).

Pokud něco v API nedohledáš, napiš mi to do README jako otevřenou otázku — neimprovizuj tiše.

## Datové zdroje

### Fáze 1 (MVP) — ARES: nové firmy
Cílení (vše editovatelné v `config/targets.yaml`):
- **Region:** Jihomoravský kraj (Brno a okolí). Připrav i možnost přidat další kraje.
- **Obory (CZ-NACE):** dej rozumný startovní seznam B2C oborů, kde firmy řeší značku — gastro (restaurace, kavárny/bary), maloobchod, výroba potravin/nápojů, kosmetika/wellness, móda, kultura/zábava, ubytování, kreativní služby apod. Ke každému kódu dej komentář, ať to umím doladit. Neber to jako dogma — klidně navrhni lepší výběr.
- **Stáří firmy:** posledních 30 dní (konfigurovatelné).

### Fáze 2 (po schválení MVP) — Webtrh poptávky: inbound
Sleduj sekci poptávek na grafiku/web na `webtrh.cz`. **Nejdřív zjisti, jestli má RSS** — pokud ano, použij ho. Pokud ne, lehký a slušný scraping: respektuj `robots.txt`, rozumné prodlevy, žádný agresivní crawl. Pokud to ToS zakazují, tuhle část přeskoč a napiš mi to. Stejnou pipeline (dedup → scoring → digest) jen napoj na další zdroj.

Architektura zdrojů ať je **pluginovatelná** — každý zdroj je modul v `src/sources/` s jednotným rozhraním (vrací list normalizovaných `Lead` objektů), takže přidat třetí/čtvrtý zdroj později je triviální.

## Datový model

Pydantic model `Lead` s normalizovanými poli napříč zdroji, např.: `source`, `external_id` (pro dedup — u ARES IČO), `name`, `nace`/`obor`, `region`, `url`, `date` (vznik/publikace), `raw` (původní payload). Scoring pak doplní `score`, `reason`, `outreach_draft`.

## Scoring přes Claude API

Modul `src/scoring.py`. Pro každý nový lead zavolej Messages API. Do system promptu vlož obsah `config/profile.md`. Žádej **striktně JSON** (žádný markdown, žádný preamble), bezpečně parsuj, ošetři chyby a rate-limit (retry s backoffem). Dávkuj rozumně.

Cílový výstup na jeden lead:
```json
{
  "score": 1-10,
  "reason": "jedna věta proč se to (ne)hodí",
  "outreach_draft": "krátký, lidský první e-mail/zpráva na míru tomu leadu"
}
```
Hodnoticí kritéria popiš v promptu: jak moc lead sedí na profil studia (obor, velikost, pravděpodobná potřeba vizuální identity). Nízké skóre = ať to v digestu spadne dolů nebo se odfiltruje (práh konfigurovatelný).

## Notifikace

Modul `src/notify.py` + `jinja2` HTML šablona. **Denní e-mail v češtině**, leady seřazené podle skóre sestupně, u každého: název, obor, region, datum vzniku, odkaz (ARES/justice), skóre, důvod a **draft oslovení** (rozbalovací nebo jasně oddělený). Nahoře krátké shrnutí (kolik nových, kolik nad prahem).

Odesílání: udělej to přes **SMTP** (konfigurovatelné přes env), ať to není vázané na jednoho providera. Pokud navrhneš jako jednodušší variantu transakční API (např. Resend), nech to za přepínačem a SMTP jako default. Adresát konfigurovatelný v `.env`.

**Nic se neodesílá leadům automaticky.** Nástroj jen připraví drafty, oslovení posílá člověk ručně po kontrole.

## Stav a deduplikace

`data/seen.json` (nebo SQLite, pokud to uznáš za lepší) drží už zpracovaná `external_id`. GitHub Actions runner je ephemeral, takže po běhu **commitni aktualizovaný stav zpět do repa** (bot commit v rámci workflow) — pro tenhle objem to bohatě stačí a je to zadarmo. Připrav i variantu „external store" jako TODO, kdyby objem narostl. Ošetři cold start (první běh): neposílej naráz stovky leadů — omez první digest na posledních N dní podle `datumVzniku`.

## Plánování (GitHub Actions)

`.github/workflows/daily.yml`:
- `schedule:` cron (denně, počítej s tím, že GH cron je v UTC a může se opozdit)
- `workflow_dispatch` pro ruční spuštění při testování
- nainstaluje deps, spustí `python main.py`, commitne stav zpět
- tajné hodnoty (`ANTHROPIC_API_KEY`, SMTP přihlášení, příjemce) **jen z GitHub Secrets**

## Bezpečnost a právo

- **Nikdy** necommituj klíče. `.env` v `.gitignore`, dodej `.env.example` s prázdnými hodnotami.
- ARES jsou veřejná open data — sběr je legální. Ale u **oslovování** přidej do README krátkou poznámku: respektovat GDPR a pravidla pro nevyžádaná obchodní sdělení (cold mail firmě s opt-outem je obvykle OK, osobní e-mail živnostníka je citlivější), proto nástroj jen připravuje podklady a člověk rozhoduje, koho a jak osloví.

## Struktura projektu (orientačně)

```
vondrart-leads/
  src/
    sources/
      base.py        # rozhraní zdroje
      ares.py        # Fáze 1
      webtrh.py      # Fáze 2
    models.py        # Lead a spol.
    scoring.py
    storage.py       # seen.json
    notify.py        # email + šablona
    config.py
  config/
    profile.md       # profil vondrart (do scoringu)
    targets.yaml     # kraj + NACE + stáří
  templates/
    digest.html.j2
  data/
    seen.json
  .github/workflows/daily.yml
  main.py            # orchestrace celé pipeline
  pyproject.toml
  .env.example
  README.md
```

## Milníky (stav se po každém zastav)

1. **Skeleton + ARES klient** — projekt, modely, `ares.py` co umí stáhnout a normalizovat nové firmy podle `targets.yaml`. Ověř proti reálnému API, vypiš pár výsledků do konzole.
2. **Dedup + storage** — `seen.json`, ošetřený cold start.
3. **Scoring** — napojení na Claude API, JSON výstup, retry/error handling.
4. **Digest e-mail** — HTML šablona, SMTP odeslání, hezky seřazené.
5. **Lokální end-to-end běh** — `python main.py` projede celou pipeline.
6. **GitHub Actions** — denní cron + commit stavu + secrets, otestovat `workflow_dispatch`.
7. **(Fáze 2)** — přidat Webtrh poptávky jako druhý zdroj.

## Na závěr dodej

- `README.md` (česky): co to dělá, jak nastavit `.env` a GitHub Secrets, jak doladit `targets.yaml` a `profile.md`, jak spustit lokálně, jak funguje cron, + sekce „otevřené otázky / co ověřit".
- `.env.example`
- Stručný kód, anglické identifikátory a komentáře, **uživatelské výstupy (e-mail, README) česky**.

Začni Milníkem 1.
