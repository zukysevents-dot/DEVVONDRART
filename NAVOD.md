# Návod: jak si u sebe rozjet lead-finder

Tenhle nástroj ti **každý den ráno sám najde nově vzniklé firmy** (z veřejného registru ARES),
ohodnotí je umělou inteligencí (jak moc se hodí jako klient) a **pošle ti je e-mailem** jako
přehledný digest s návrhem, jak je oslovit. Běží zdarma na GitHubu — **nemusíš mít žádný server
ani počítač zapnutý.**

Celé nastavení zabere ~20 minut a zvládneš ho přes web, nic se neinstaluje.

---

## Co budeš potřebovat
1. **Účet na GitHubu** (zdarma) — https://github.com
2. **Anthropic API klíč** (pohání to hodnocení) — pár dolarů kreditu, hodnocení jedné firmy stojí zlomek centu.
3. **E-mail, ze kterého se bude posílat** (např. Gmail nebo Seznam) — kam ti digest přijde, si zvolíš.

---

## Krok 1 — Zkopíruj si projekt k sobě (Fork)
1. Otevři repo: **https://github.com/zukysevents-dot/DEVVONDRART**
2. Vpravo nahoře klikni na **Fork** → **Create fork**.
   Tím vznikne tvoje vlastní kopie (`github.com/TVŮJ-ÚČET/DEVVONDRART`), kterou si můžeš upravovat
   a běží ti pod tvým účtem.

> Když chceš kopii **soukromou** (aby ji nikdo neviděl), napiš mi — poradím, jak ji místo forku
> naimportovat jako private repo. Ale pro běh to není nutné (jména firem jsou stejně veřejná data).

---

## Krok 2 — Získej Anthropic API klíč
1. Jdi na **https://console.anthropic.com** a zaregistruj se (klidně přes Google).
2. Vlevo **Settings → Billing** → přidej kartu a **nabij si kredit** (stačí pár dolarů). Bez kreditu to nepojede.
3. Vlevo **API keys → Create key**, pojmenuj třeba `lead-finder`, **Create**.
4. Klíč (`sk-ant-…`) se ukáže **jen jednou** → zkopíruj si ho stranou. Budeš ho potřebovat v kroku 4.

---

## Krok 3 — Připrav e-mail pro odesílání (SMTP)

### Varianta A — Gmail (nejběžnější)
Gmail nepustí přihlášení běžným heslem, potřebuješ **„heslo aplikace"**:
1. Zapni si dvoufázové ověření: https://myaccount.google.com/security → **2-Step Verification**.
2. Pak jdi na **https://myaccount.google.com/apppasswords**, vytvoř heslo aplikace (název třeba `lead-finder`).
3. Vznikne **16místné heslo** (např. `abcd efgh ijkl mnop`) — zkopíruj ho **bez mezer**.

Údaje pro krok 4:
- `SMTP_HOST` = `smtp.gmail.com`
- `SMTP_PORT` = `587`
- `SMTP_USER` = tvoje gmailová adresa
- `SMTP_PASSWORD` = to 16místné heslo aplikace (bez mezer)
- `DIGEST_FROM` = tvoje gmailová adresa
- `DIGEST_TO` = kam chceš digest dostávat (klidně stejný gmail)

### Varianta B — Seznam.cz
- `SMTP_HOST` = `smtp.seznam.cz`
- `SMTP_PORT` = `465`
- `SMTP_USER` / `DIGEST_FROM` = tvoje @seznam.cz adresa
- `SMTP_PASSWORD` = heslo k e-mailu (Seznam má někdy „heslo pro aplikace" v nastavení schránky)
- `DIGEST_TO` = kam to chceš

---

## Krok 4 — Vlož tajné údaje do GitHub Secrets
Klíče **nikdy nepiš přímo do kódu** — patří do Secrets (jsou šifrované, nikdo je nevidí).

1. Ve své kopii repa jdi na **Settings** (nahoře) → vlevo **Secrets and variables → Actions**.
2. Klikni **New repository secret** a postupně přidej tyhle (vždy název + hodnota → Add secret):

| Název (Name) | Hodnota (Secret) |
|---|---|
| `ANTHROPIC_API_KEY` | tvůj `sk-ant-…` klíč |
| `SMTP_HOST` | např. `smtp.gmail.com` |
| `SMTP_PORT` | `587` (Gmail) nebo `465` (Seznam) |
| `SMTP_USER` | tvoje e-mailová adresa |
| `SMTP_PASSWORD` | heslo aplikace / heslo schránky |
| `DIGEST_FROM` | tvoje e-mailová adresa |
| `DIGEST_TO` | kam chceš digest dostávat |

> Názvy musí sedět **přesně** (velkými písmeny, podtržítka). Hodnoty kdykoli změníš tlačítkem Update.

---

## Krok 5 (volitelné) — Uprav si cílení a profil studia
Ve výchozím stavu to hledá **v Brně a okolí** firmy z oborů jako gastro, kavárny, pekařství, kosmetika,
móda apod. Když ti to sedí, nemusíš měnit nic. Jinak si na GitHubu otevři a uprav (tužka „Edit"):

- **`config/targets.yaml`** — region (kraj a obce), obory (CZ-NACE kódy), stáří firem (`max_age_days`).
- **`config/profile.md`** — popis tvého studia/byznysu. Tenhle text čte AI při hodnocení, takže ho
  klidně přepiš na sebe (co děláš, pro koho, jaký klient se ti hodí). Čím přesnější, tím lepší skóre.

> **Jsi v jiném městě / kraji než Brno?** Pak je potřeba doplnit správné kódy kraje a obcí — to není
> úplně samozřejmé (ARES je nemá hezky pojmenované). Napiš mi tvoje město/region a já ti ty kódy
> připravím a pošlu hotový `targets.yaml`.

---

## Krok 6 — Zapni to a otestuj
1. Ve své kopii repa jdi nahoře na záložku **Actions**.
2. Když uvidíš hlášku, že workflows jsou na forku vypnuté → klikni **„I understand my workflows,
   go ahead and enable them."**
3. Vlevo vyber workflow **daily-leads** → vpravo **Run workflow** → **Run workflow** (na větvi `main`).
4. Po pár minutách by měl běh zezelenat (✓) a **měl by ti přijít e-mail** s nalezenými firmami.
   (Kdyby nepřišel, mrkni do spamu a do Krok 4, jestli sedí SMTP údaje.)

**A to je vše.** Od teď to běží **automaticky každý den ráno** (kolem 8:00) a posílá ti čerstvé firmy.
Stejná firma ti nepřijde dvakrát — nástroj si pamatuje, co už poslal.

---

## Časté otázky

**Kolik to stojí?** GitHub Actions i ARES jsou zdarma. Platíš jen Anthropic kredit — řádově pár korun
měsíčně podle počtu firem. Posílání e-mailů přes Gmail/Seznam je zdarma.

**Kam ty firmy chodí?** Na e-mail v `DIGEST_TO`. Seřazené podle toho, jak se ti hodí (skóre 1–10),
u každé je důvod a návrh prvního oslovení.

**Posílá to něco těm firmám samo?** **Ne.** Nástroj jen připraví podklady tobě. Koho a jak oslovíš,
rozhoduješ ty (a hlídej si GDPR / pravidla pro nevyžádaná obchodní sdělení).

**Chci to spustit ručně mimo ráno.** Actions → daily-leads → Run workflow.

**Přestalo to po čase chodit?** GitHub uspí automatické běhy na forku po delší nečinnosti — stačí
zajít do **Actions** a workflow znovu povolit / spustit ručně.

**Potřebuju s něčím pomoct (jiný region, jiné obory, e-mail nejde)?** Napiš — nejrychlejší je poslat,
co přesně vidíš (chybová hláška z Actions / že nepřišel mail), a doladíme to.
