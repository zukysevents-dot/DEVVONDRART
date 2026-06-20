# vondrart lead-finder

Nástroj, který **každý den automaticky vyhledává nově vzniklé firmy** v relevantních
oborech a regionu (zdroj **ARES**), ohodnotí je přes **Claude API** (fit 1–10 + důvod +
návrh oslovení) a pošle **e-mailový digest v češtině** seřazený podle skóre. Běh řídí
**GitHub Actions cron** (žádný démon, žádný MCP server). Stav (deduplikace) se drží
v `data/seen.json` a commituje se zpět do repa.

> **Stav:** rozpracováno po milnících. Hotovo: **Milník 1 — skeleton + ARES klient.**

## Co to dělá (cílový stav)

1. **Sběr** nových firem ze zdrojů (Fáze 1: ARES; Fáze 2: Webtrh poptávky)
2. **Deduplikace** proti `data/seen.json`
3. **Scoring** přes Claude API — fit 1–10, jedna věta proč, návrh prvního oslovení
4. **Digest** — denní HTML e-mail (česky), seřazený podle skóre
5. **Plánování** — GitHub Actions cron, jednou denně

**Nic se neodesílá leadům automaticky.** Nástroj jen připraví podklady; koho a jak
oslovit, rozhoduje člověk (viz [Právo a GDPR](#právo-a-gdpr)).

## Tech stack

Python 3.11+, `httpx`, `anthropic` SDK (`claude-sonnet-4-6`), `pydantic` v2,
`pydantic-settings`, `jinja2`, `pyyaml`. Plánovač: GitHub Actions. Stav: `data/seen.json`.

## Struktura

```
src/
  sources/
    base.py        # jednotné rozhraní zdroje
    ares.py        # Fáze 1 — ARES
  models.py        # Lead
  config.py        # .env (pydantic-settings) + targets.yaml
config/
  profile.md       # profil studia (vstupuje do scoringu)
  targets.yaml     # kraj/obce + NACE + stáří firem
data/              # seen.json — stav deduplikace (vytvoří se za běhu)
tests/
main.py            # orchestrace pipeline
pyproject.toml
.env.example
```

## Instalace a spuštění (lokálně, Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Milník 1: stáhne nové firmy z ARES a vypíše je do konzole (BEZ jakýchkoli klíčů).
python main.py

# Testy
pytest
```

Na macOS/Linux je aktivace `source .venv/bin/activate`.

## Konfigurace

### `config/targets.yaml` — co a kde hledat
- `kraj_codes` — klientská kontrola kraje z odpovědi ARES (`116` = Jihomoravský).
- `max_age_days` — jak staré firmy brát jako „nové" (default 30).
- `localities` — územní cíle; každý `filter` je fragment ARES `AdresaFiltr`
  (`kodObce`, nebo u velkých měst `kodMestskeCastiObvodu`).
- `nace` — seznam CZ-NACE 2025 kódů (5místné) s popiskem; doleď podle potřeby.

### `config/profile.md` — profil studia
Text se vkládá do promptu hodnoticího modelu (Milník 3). Uprav, ať skóre sedí.

### `.env` — tajné hodnoty (NIKDY do gitu)
Zkopíruj `.env.example` na `.env`. Pro Milník 1 **není potřeba nic vyplňovat**.
Klíče (Anthropic, SMTP) přijdou v Milníku 3 a 4; v CI půjdou do **GitHub Secrets**.

## ARES — jak je klient postavený (a co bylo ověřeno)

Klient používá veřejné REST API ARES (otevřená data MF, bez registrace):

- Base: `https://ares.gov.cz/ekonomicke-subjekty-v-be/rest`
- Hledání: `POST /ekonomicke-subjekty/vyhledat` s JSON filtrem
  (`EkonomickeSubjektyKomplexFiltr`)

Dotazuje se po **segmentech (lokalita × NACE)**, stáhne celý segment a klientsky
ponechá jen firmy s `datumVzniku` v posledních `max_age_days` dnech. Když segment
přeteče strop 1000 (typicky gastro ve velkém městě), klient **automaticky zúží
dotaz na nakonfigurované městské části** (`mestske_casti` u lokality v `targets.yaml`).

## Stav a deduplikace (`data/seen.json`)

Zpracovaná `external_id` (klíč `source:external_id`, u ARES `ares:<IČO>`) se ukládají do
`data/seen.json`, aby stejný lead nechodil v digestu dokola. Zápis je atomický.

- **Cold start (první běh):** stav je prázdný → vše v okně je „nové". Pojistka
  `max_new_per_run` (default 100, env `MAX_NEW_PER_RUN`) omezí počet notifikovaných na
  běh; přebytek se označí jako viděný bez notifikace, aby první digest nebyl o stovkách.
- Soubor je v Milníku 6 commitován zpět do repa botem (GitHub Actions runner je ephemeral).
- Stav se zapisuje až po zpracování běhu (od Milníku 4/5 až po odeslání digestu).

## Scoring (Claude API)

Modul [src/scoring.py](src/scoring.py) pošle každý nový lead na Claude (`claude-sonnet-4-6`,
konfigurovatelné přes `ANTHROPIC_MODEL`). Profil studia z `config/profile.md` se vkládá do
system promptu. Model vrací **striktní JSON**:

```json
{"score": 1-10, "reason": "jedna věta proč se (ne)hodí", "outreach_draft": "návrh prvního oslovení"}
```

Výstup se bezpečně parsuje (odolný vůči markdownu/textu navíc, skóre se ořízne na 1–10),
rate-limit a přechodné chyby se opakují s exponenciálním backoffem. Bez `ANTHROPIC_API_KEY`
se scoring přeskočí (leady zůstanou bez skóre). Práh `score_threshold` (default 5) využije
digest v Milníku 4. **Nic se neodesílá leadům** — drafty jen připraví, oslovení řeší člověk.

Ostrý test scoringu (po vyplnění `.env`):
```powershell
$env:MAX_AGE_DAYS=90; python main.py   # u každého leadu uvidíš skóre, důvod a návrh oslovení
```

## Digest e-mail (SMTP)

Modul [src/notify.py](src/notify.py) + šablona [templates/digest.html.j2](templates/digest.html.j2)
sestaví **denní HTML e-mail v češtině**: nahoře shrnutí (kolik nových, kolik nad prahem),
pak karty leadů seřazené podle skóre — název, skóre, obor/region/datum, důvod, **návrh
oslovení** a odkaz do ARES. Leady pod prahem `score_threshold` se do digestu nedostanou.

- Odesílá se přes **SMTP** (`SMTP_HOST/PORT/USER/PASSWORD`, `SMTP_USE_TLS`; port 465 = SSL,
  jinak STARTTLS). Odesílatel `DIGEST_FROM`, příjemce `DIGEST_TO`.
- **Bez SMTP** se e-mail neodesílá — místo toho se uloží **náhled** do
  `data/digest_preview.html` (otevři v prohlížeči). Stav se v náhledovém režimu neukládá.
- Stav `seen.json` se zapíše **až po úspěšném odeslání** — když odeslání selže, leady se
  zkusí příště (nic se neztratí).

## Druhý zdroj — Webtrh poptávky (Fáze 2)

[src/sources/webtrh.py](src/sources/webtrh.py) přidává **inbound leady** z poptávek na
grafiku/design na webtrh.cz. Architektura zdrojů je pluginovatelná (`src/sources/base.py`),
takže Webtrh běží stejnou pipeline (dedup → scoring → digest) jako ARES.

- **Default vypnuto.** Zapni v `config/targets.yaml`:
  ```yaml
  webtrh:
    enabled: true
  ```
- Webtrh **nemá funkční RSS** (ověřeno), proto se čte **jeden výpis kategorie** poptávek
  (název, odkaz, kategorie, rozpočet, relativní datum). Žádný agresivní crawl.
- **Právně ověřeno:** `robots.txt` zakazuje jen `/wp-admin/`; podmínky užívání nezakazují
  automatizovaný přístup (omezují jen *vkládání* obsahu). Slušný User-Agent, jeden GET.

## Nasazení (GitHub Actions)

Workflow [.github/workflows/daily.yml](.github/workflows/daily.yml) běží **denně přes cron**
(`0 6 * * *` = 06:00 UTC; GitHub cron je v UTC a může se opozdit) a jde spustit i ručně
přes **workflow_dispatch**. Krok za krokem: checkout → setup Python 3.11 → `pip install -e .`
→ `python main.py` → **commit aktualizovaného `data/seen.json` zpět do repa** (bot,
`permissions: contents: write`).

### Nastavení GitHub Secrets (tajné hodnoty jen sem, ne do kódu)

V **GitHub → Settings → Secrets and variables → Actions → New repository secret**, nebo
přes `gh` (hodnotu zadáš skrytě, nikam ji nevkládej do chatu):

```bash
gh secret set ANTHROPIC_API_KEY     # klíč z console.anthropic.com
gh secret set SMTP_HOST
gh secret set SMTP_USER
gh secret set SMTP_PASSWORD
gh secret set DIGEST_FROM           # odesílatel
gh secret set DIGEST_TO             # příjemce digestu
# volitelné (mají rozumný default):
gh secret set SMTP_PORT             # default 587 (465 = SSL)
gh secret set SMTP_USE_TLS          # default true
gh secret set ANTHROPIC_MODEL       # default claude-sonnet-4-6
```

Bez nastavených secrets workflow **nespadne** — jen poběží v náhledovém režimu (bez scoringu
a bez odeslání). Po nastavení otestuj ručně: **Actions → daily-leads → Run workflow**
(nebo `gh workflow run daily-leads`).

## Otevřené otázky / co ověřit

Ověřeno proti živému ARES API (ne z paměti) — a narazili jsme na omezení, která
určují celý návrh sběru:

1. **Filtr neumí datum vzniku ani řazení podle data.** Pole filtru jsou jen `ico`,
   `obchodniJmeno`, `sidlo` (AdresaFiltr), `pravniForma`, `financniUrad`, `czNace`.
   Řazení (`razeni`) podporuje jen `icoId`, `obchodniJmeno`, `nazevObce`
   (`-datumVzniku` je odmítnuto). → „nové za posledních N dní" filtrujeme **klientsky**.
2. **Filtr neumí kraj ani okres.** Nejmenší územní filtr je **obec** (`kodObce`),
   u velkých měst lze zúžit na **městskou část** (`kodMestskeCastiObvodu`).
   Kraj je jen v odpovědi (`sidlo.kodKraje`) → kontrolujeme ho klientsky.
3. **Strop 1000 výsledků na dotaz** (na CELKOVÝ počet shod). Segment proto musí mít
   v historii < 1000 firem. Příklad: *Brno × restaurace (56110) = 7 790* → ARES dotaz
   odmítne. Řešení: klient přetékající segment **automaticky zúží na městské části**
   (`mestske_casti` v `targets.yaml`). Pozn.: i nejhustší *Brno-střed × restaurace*
   zůstává přes strop — to by chtělo ještě jemnější dělení na části obce
   (`kodCastiObce`); zatím se taková MČ zaloguje a přeskočí.
4. **Zpoždění dat (důležité pro `max_age_days`).** Ověřeno: nejnovější `datumVzniku`
   napříč ARES je řádově ~30 dní starý (firmy se do registru propisují s odstupem).
   Okno přesně 30 dní k „dnešku" proto v praxi nechytí skoro nic. Default v
   `targets.yaml` je proto nastaven na **60** (konfigurovatelné přes env `MAX_AGE_DAYS`).
5. **Význam `datumVzniku`** ověřen (detail firmy): je to skutečné datum vzniku,
   subjekty jsou `AKTIVNI` a bez `datumZaniku` → jde o reálně nové firmy. Pozor: české
   IČO **nejsou striktně chronologická**, proto se „nové" pozná podle data, ne podle IČO.
6. **CZ-NACE se matchuje přesně** (5místné kódy, ne prefix). Kódy v `targets.yaml`
   jsou ověřené, že v Brně vracejí data pod stropem; doplnění dalších oborů (služby
   jako kadeřnictví/kosmetické služby, online retail) vyžaduje dohledat platný
   5místný kód CZ-NACE 2025.
7. **Pokrytí celého kraje** (ne jen vybraných obcí) by vyžadovalo statický seznam
   obcí JMK, případně bulk open-data export ARES. Zatím cílíme na vyjmenované obce
   (default: Brno (27 z 29 MČ) + okolí) — rozšiřitelné v `targets.yaml`.
8. **Webtrh:** u některých „Redakčních" poptávek chybí ve výpisu kategorie nebo datum
   (jiná struktura bloku) — lead se i tak vytvoří (dedup řeší „nové"). Pro plný popis
   k scoringu by šlo dotáhnout detail poptávky, ale to znamená víc requestů; zatím
   držíme lehký jeden-GET přístup.

## Právo a GDPR

ARES jsou veřejná open data — sběr je legální. U **oslovování** ale platí: respektovat
GDPR a pravidla pro nevyžádaná obchodní sdělení. Cold mail firmě s možností opt-out je
obvykle v pořádku, osobní e-mail živnostníka je citlivější. Proto nástroj jen připravuje
podklady a o oslovení rozhoduje člověk. Klíče se **nikdy** necommitují (`.env` v `.gitignore`).

## Roadmap (milníky)

1. ✅ **Skeleton + ARES klient**
2. ✅ **Dedup + storage** (`data/seen.json`, cold start)
3. ✅ **Scoring** (Claude API, JSON výstup, retry)
4. ✅ **Digest e-mail** (Jinja2 + SMTP)
5. ✅ **Lokální end-to-end běh** (`python main.py` projede celou pipeline)
6. ✅ **GitHub Actions** (cron + commit stavu + Secrets)
7. ✅ **(Fáze 2)** Webtrh poptávky jako druhý zdroj
