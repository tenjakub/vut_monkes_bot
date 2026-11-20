# AGENTS.md – pokyny pro AI agenty (Claude Code a další)

Tenhle soubor je pro AI, která na projektu pracuje. Lidský návod je v [README.md](README.md).

## O projektu

- **VUT Monkes bot** – Discord bot pro kamarádský server studentů VUT (FIT). Python 3.14, discord.py 2.x.
- Commandy: `/ppv`, `/purkyne`, `/menzy` (menzy VUT), `/restaurace` (polední menu), `/mhd`, `/mhd-purkyne` (odjezdy MHD Brno).
- **Celý kód píše AI.** Majitel repa zadává požadavky, testuje na Discordu a rozhoduje. Kód nepíše, ale čte ho.
- **Jazyk:** komunikace s uživatelem, texty v botovi, komentáře, docstringy i commit zprávy jsou **česky**.
  Identifikátory v kódu jsou anglicky.

## Spolupráce s uživatelem

- Commit dělej, když o něj uživatel požádá nebo když dokončíš úkol, na kterém jste se domluvili.
  Commit zprávy končí řádkem `Co-Authored-By: …` podle pokynů prostředí. **Pushuj jen na výslovnou žádost**,
  protože push do `main` = automatické nasazení na produkci.
- Uživatel testuje výsledek sám na Discordu a posílá screenshoty. Vždy řekni, co jsi ověřil a co ne
  (typicky: „v Discordu jsem to neviděl“).
- Preference: příkazy na jedno kliknutí (raději víc commandů než parametry), přehledné kartičky v mřížce,
  emoji. Méně důležité informace spíš nevýrazně než vůbec.

## Vývoj a testy

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # musí projít před každým commitem
.venv/bin/python bot.py                # lokální běh (vývojový bot, token v .env)
```

- Lokálně se vyvíjí **přímo v Pythonu**. Docker se používá jen pro produkční nasazení.
- Lokální `.env` obsahuje token **vývojového** bota. Nikdy ho necommituj ani nečti nahlas.
  Nespouštěj bota se skutečným tokenem bez souhlasu uživatele, mohl by kolidovat s běžící instancí.
- Testy jsou offline: uložené HTML stránky v `tests/fixtures/` a syntetické mini-GTFS v `tests/test_transit.py`.
  Nový scraper = ulož fixture + přidej test.
- Pro ověření na živých datech stačí zavolat `build_message(...)` z cogu s `SimpleNamespace(fetcher=Fetcher())`
  a vypsat embedy. Na Discord se připojovat není potřeba.
- Verze Pythonu musí sedět na třech místech: lokální venv, `Dockerfile` (`python:3.14-slim`), CI (`setup-python`).

## Architektura

```
bot.py            ObedBot: načte cogy, sync commandů, heartbeat pro healthcheck
cogs/             Discord vrstva – každý cog má build_message() -> (content, embeds, view)
lunch/            menzy a restaurace, BEZ závislosti na discord.py
transit/          MHD (GTFS), BEZ závislosti na discord.py
utils/render.py   Field (kartička), mřížka, limity embedů, header s časem
```

Pravidla:
- `lunch/` a `transit/` neimportují `discord`. Logika a parsování patří tam, vykreslování do `cogs/` a `utils/render.py`.
- **Tlačítka jsou `discord.ui.DynamicItem`** a stav mají v `custom_id` (např. `menza:ppv:eco:g`, `mhd:vse:r`).
  Fungují i po restartu bota na starých zprávách. Při změně šablony custom_id mysli na staré zprávy:
  neznámý stav ošetři hláškou „Tohle tlačítko už je zastaralé.“, nepadej.
- Odpovědi: slash command → `defer(thinking=True)` → `followup.send`. Tlačítko → `defer()` → `edit_original_response`.
- Chyby jednoho zdroje nesmí shodit celý výpis: `Menu(error=...)` → embed s ⚠️, ostatní zdroje se zobrazí.

### Discord – limity a záludnosti

- Max 10 embedů na zprávu a **6000 znaků dohromady**, 25 fieldů na embed, 5 tlačítek v řadě.
  `render.per_embed_limit()` a `render.add_fields()` to hlídají, nové výpisy je musí používat.
- **Embedy se stejnou `url` Discord sloučí do jednoho** (jeden pak zmizí). Každý embed ve zprávě musí mít
  unikátní URL (u MHD proto `…#technopark`, `…#kolejni`). Hlídá to test.
- Inline fieldy tvoří mřížku po 3. `add_fields()` doplňuje poslední řadu prázdnými fieldy, jinak se osamocená
  kartička roztáhne přes celou šířku.
- Časy zobrazuj jako Discord timestampy `<t:UNIX:t>` / `<t:UNIX:R>` (lokalizované, samy se aktualizují).
- Při nastaveném `GUILD_IDS` bot commandy kopíruje na servery a **maže globální commandy** (jinak by byly dvakrát).

## Oprávnění a intenty – kontrola při každé změně

Aktuální stav (ověřeno pro verzi s `/ppv`, `/purkyne`, `/menzy`, `/restaurace`, `/mhd`, `/mhd-purkyne`):

- **Intenty:** `discord.Intents.default()`, žádné privilegované (Message Content, Server Members, Presence vypnuté).
- **Oprávnění bota:** View Channels, Send Messages, Embed Links → číselně `19456`.
  Bot dnes komunikuje **jen přes odpovědi na interakce** (slash commandy, tlačítka) a sám do kanálů nic neposílá.
- **Scopes:** `bot` + `applications.commands`, Integration Type *Guild Install*.

Když změna přidává něco z tohoto seznamu, je potřeba upravit oprávnění/intenty:

| Nová funkce | Potřeba |
|---|---|
| bot sám posílá zprávy (plánované, notifikace) přes `channel.send` | View Channels + Send Messages v daném kanálu (už máme) |
| čtení obsahu zpráv / prefix commandy | privilegovaný intent **Message Content** (zapnout v portálu i v kódu) |
| reakce | **Add Reactions** (+ Read Message History pro reakce na starší zprávy) |
| obrázky / soubory | **Attach Files** |
| vlákna | **Send Messages in Threads**, případně **Create Public Threads** |
| role, přezdívky, moderace | konkrétní Manage oprávnění + nejspíš intent **Server Members** |
| vlastní emoji ze serveru | **Use External Emojis** |

Postup, když jsou nová oprávnění potřeba:
1. Uprav sekci „Oprávnění“ a číslo `permissions=` v pozvánce v [README.md](README.md) a tuhle sekci.
2. **Výslovně řekni uživateli**, že musí v Developer Portalu zapnout intent nebo bota přidat se novým odkazem
   (případně přidat oprávnění roli bota na serveru). Platí to pro **oba boty, vývojového i produkčního**.
   Už pozvaní boti nová oprávnění sami nedostanou.

## Zdroje dat a jejich záludnosti

**Menzy – KaM VUT** (`lunch/kam.py`): `https://www.kam.vut.cz/?p=menu&provoz=<ID>`, ID na `?p=otdo`.
- Tabulka `table#m<ID>`, česky název ve `td.jjjaz1jjj`, alergeny v `<small>`.
- Economy jídla = název začíná `Economy N:`. Typ: `P` polévka, `H` hlavní, `O` ostatní (saláty, přílohy) – ty se nezobrazují.
- Ceny: `slcen1` student VUT (zobrazujeme), `slcen2` zaměstnanec, `slcen3` externí, `slcen4` student jiné VŠ.
- KaM průběžně maže vyprodaná jídla, proto krátká cache (5 min).
- Otevírací doby: `kam.parse_hours` z `?p=otdo` (`table.ntab`, sloupce PO–ČT / PÁ / SO+NE). Den před státním
  svátkem = PÁ, svátek = SO+NE (`kam.cz_holidays`, včetně Velikonoc). Sloupec stavu je jen aktuální stav
  (mimo provoz „z“), používá se jen `x` a `a`. Zobrazuje se v patičce kartičky menzy („🕐 Dnes …“).

**Restaurace** (`lunch/service.py` → `RESTAURANTS`):
- menicka.cz (`menicka.py`): blok `div.menicka` se hledá podle data v nadpisu, ne podle pořadí.
  Alergeny bývají jako `<em>1</em>` uvnitř názvu a vyhazují se. Nová restaurace = ID z URL + řádek v `RESTAURANTS`.
- La Strada má vlastní web (`lastrada.py`): týdenní karty `.ls-card`, ceny v `.ls-pricing`. Je to nejkřehčí scraper.

**MHD – KORDIS JMK** (`transit/`), otevřená data CC BY:
- Statické GTFS `https://kordis-jmk.cz/gtfs/gtfs.zip` (~6 MB, `stop_times` ~28 MB). Načítá se jen to, co je
  potřeba pro zastávky z `BOARDS`, mimo event loop (`asyncio.to_thread`), uloží se do `data/` (volume v Dockeru).
- Tabule a oblasti jsou v `transit/service.py` (`BOARDS`, `AREAS`). Tabule může být jen část zastávky
  (`platforms` = stop_id nástupišť, např. Skácelova → východ `U1567Z6` / západ `U1567Z5`). Kartičky skládá
  `cogs/mhd._cards` podle `Board.layout`:
  `merge` = jedna kartička na nástupiště „Tram → <směr>“ (směr z `directions`, jinak obvyklá konečná), u každého
  času `` `linka` `` (Technopark, Červinkova); `lines` = kartička na linku + nástupiště, řazeno podle čísla linky,
  nadpis = obvyklá konečná z celého JŘ (`Timetable.usual_headsign`), jiné konečné jako značka (Skácelova);
  `auto` = podle linky a cíle, `merged_lines` bez cíle (65), `continuing` = popisek směru pokračujících spojů,
  připnuté první (72 → Semilasso), končící spoje nevýrazně na konci (Kolejní).
- Oblast `vse` = „PPV“ (koleje Pod Palackého vrchem), `purkyne` = koleje Purkyňova.
- Klíč oblasti `vse` (Technopark + Kolejní) se nesmí přejmenovat – je v `custom_id` tlačítek na starších zprávách.
- GTFS nemá `block_id`. Navazující spoj se odvozuje: příjezd na nástupiště P v čase A → spoj stejné linky
  z P v okně A…A+5 min. Na lince 72 (Technologický park: Z4 = jede dál, Z3 = končí) to sedí.
- GTFS Realtime `https://kordis-jmk.cz/gtfs/gtfsReal.dat`: **jen VehiclePositions + Alerts, žádné TripUpdates**
  (zpoždění chybí). `trip_id` v RT **nesedí** na statické GTFS (stav 2026-11), RT `stop_id` mají nuly navíc
  (`U01108Z02` vs `U1108Z2`). Používáme jen výluky. U nich je `route_id` = číslo linky („72“).
- **Nepoužívej API mapy `mapa.idsjmk.cz`** (vyžaduje `X-Access-Token` z webu, jde o neautorizovaný přístup)
  ani nedokumentované `/api/departures` na idsjmk.cz. Živá zpoždění až s oficiálním přístupem od KORDIS,
  o který chce uživatel požádat.

Obecně: na weby chodíme s cache (`lunch/fetcher.py`) a slušným User-Agentem, žádné agresivní dotazování.

## Nasazení

- Push do `main` → GitHub Actions (`.github/workflows/ci.yml`): testy → build image →
  `ghcr.io/tenjakub/vut_monkes_bot:latest` + `:sha-<commit>`.
- Homelab (AlmaLinux, Portainer): `docker-compose.yml` = bot + Watchtower.
  Používáme fork **`nickfedor/watchtower`**, protože původní `containrrr/watchtower` je archivovaný a s novým Dockerem
  nefunguje. Watchtower má scope `vut-monkes-bot` a hlídá jen tenhle stack.
- SELinux: bot má named volume (`bot_data`), Watchtower má `security_opt: label=disable` kvůli `docker.sock`.
- Healthcheck: bot každých 30 s „dotkne“ `HEALTH_FILE`, jen když je připojený. `healthcheck.py` kontroluje stáří.
- Dva boti: **vývojový** (lokálně, testovací server) a **produkční** (Docker, hlavní server). Stejný kód,
  jiný token a `GUILD_IDS`.
- Nové runtime závislosti patří do `requirements.txt` (jinak je image nebude mít), testovací do `requirements-dev.txt`.
