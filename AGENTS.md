# AGENTS.md – pokyny pro AI agenty (Claude Code a další)

Tenhle soubor je pro AI, která na projektu pracuje. Lidský návod je v [README.md](README.md).

## O projektu

- **VUT Monkes bot** – Discord bot pro kamarádský server studentů VUT (FIT). Python 3.14, discord.py 2.x.
- Commandy: `/ppv`, `/purkyne`, `/menzy` (menzy VUT), `/restaurace` (polední menu), `/mhd`, `/mhd-purkyne` (odjezdy MHD Brno),
  `/letaky`, `/maso`, `/napoje`, `/pivo` (letáky a slevy supermarketů), `/domu` (spoje z centra na koleje),
  `/obed` (kdo jde na oběd), `/na-pivo`, `/na-pivo-termin` (domluva na pivo), `/co-jist` (náhodné jídlo), `/pocasi`,
  `/novinky` (changelog).
- Repo je veřejné, kód je pod licencí MIT ([LICENSE](LICENSE)). Data ze zdrojů patří jim (viz README → Licence).
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

## Branche a vydávání verzí

`main` = produkce. Každý push do `main` se do pár minut nasadí na server kamarádů (CI → GHCR → Watchtower).

- **Na `main` se přímo nevyvíjí.** Každá nová funkce nebo oprava vzniká ve vlastní branchi založené z aktuálního `main`:
  `feature/<krátký-popis>` pro novinky, `fix/<krátký-popis>` pro opravy (anglicky nebo česky bez diakritiky,
  malými písmeny, s pomlčkami). Na začátku práce zkontroluj `git status` a branch. Pokud jsi na `main`,
  založ branch dřív, než cokoli změníš.
- Jedna branch = jedno téma. Nesouvisející věci patří do jiné branche.
- **Nezakládej branch pro každou úpravu.** Další kola zpětné vazby, doladění a drobnosti ke stejnému tématu
  (např. „ještě u /pivo…“, „a u /domu…“ po testování) pokračují ve **stejné branchi**, dalšími commity. Platí to,
  i když uživatel mezitím branch začlenil do `main`: přepni se na ni, `git merge --ff-only main` a pokračuj (když
  byla smazaná, založ ji znovu se stejným názvem z `main`). Novou branch zakládej jen pro opravdu nové, nesouvisející
  téma. Žádné řetězení `xyz-2`, `xyz-3`… nad nezačleněnými branchemi.
- Lokální vývojový bot může běžet z jakékoli branche, na produkci jde jen `main`.
- Push feature branche je bezpečný (CI v ní jen pustí testy, nic nenasazuje), ale i tak jen na žádost uživatele.
- **Historie je lineární, bez merge commitů.** Před začleněním branch přeskládej na aktuální `main`
  a do `main` ji pusť jen jako fast-forward:

  ```bash
  git fetch origin
  git rebase origin/main            # ve feature branchi; konflikty vyřešit, pustit testy
  git switch main && git pull --ff-only
  git merge --ff-only feature/xyz   # žádný merge commit
  git push origin main              # = nasazení, jen na výslovný pokyn uživatele
  git branch -d feature/xyz && git push origin --delete feature/xyz   # úklid (pokud byla pushnutá)
  ```

  Pull requesty nejsou povinné (vyvíjí jeden člověk). Pokud ho uživatel přesto chce, sloučit přes **Rebase and merge**.
- Rebase jen vlastních, ještě nezačleněných branchí. `main` se nikdy nepřepisuje (žádný force push).

### CHANGELOG.md a verze

- [CHANGELOG.md](CHANGELOG.md) je pro **uživatele na Discordu**. Bot ho ukazuje v `/novinky` a nejnovější verze
  je ve statusu bota (`verze 1.1 · <commit>`). Píše se česky, srozumitelně, klidně s emoji. Nepatří tam
  refaktoring, testy, CI, dokumentace ani drobné QoL úpravy, které uživatel nepozná.
- Formát nadpisu musí přesně odpovídat `## <verze> · <RRRR-MM-DD> · <krátký název>`, nejnovější nahoře.
  Hlídá to `tests/test_changelog.py`.
- Číslo verze: nová funkce → `1.x` (minor, např. 1.1 → 1.2), oprava chyby → `1.x.y` (např. 1.2 → 1.2.1).
  Velké předělávky → `2.0` (jen po domluvě).
- Změna viditelná pro uživatele = v její branchi přidej (nebo rozšiř) záznam nahoře v CHANGELOG.md.
  Datum je den vydání. Když se branch začleňuje později, datum při rebase před začleněním aktualizuj.
- **Záznam popisuje jen rozdíl proti předchozí vydané verzi**, ne průběh vývoje. Uživatel zná jen to, co
  bylo na produkci; vývojové mezikroky nikdy neviděl.
  - Vydaná verze = nejvyšší verze v CHANGELOG.md na `origin/main`. Všechno nad ní je ještě nevydané.
  - Úpravy funkce, která ještě nebyla vydaná (ladění vzhledu, přejmenování, přidané filtry, opravy chyb
    vzniklých během vývoje…), se nepíšou jako další odrážky. Nevydaný záznam se místo toho **přepíše**,
    aby popisoval výslednou podobu funkce.
  - Špatně: „/pivo ukazuje pivo v akci“ + „piva se teď jmenují zkráceně“ + „opravena duplicita“
    (vše ve stejné nevydané verzi). Správně: jedna odrážka, jak `/pivo` vypadá při vydání.
  - Změna už vydané funkce (např. přejmenování commandu, který je na produkci) do záznamu patří.
  - Když se najednou vydává víc nevydaných verzí, každá popisuje jen svoje novinky proti verzi pod ní
    a nic z ní nesmí popisovat mezistav, který nikdo neviděl.
  - Před vydáním projdi všechny nevydané záznamy očima uživatele, který zná jen poslední vydanou verzi.
- Commit hash (`BOT_VERSION`) dál slouží k přesné identifikaci buildu a sedí s tagem image `sha-<hash>`.

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
shops/            slevy a letáky z Kupi.cz, BEZ závislosti na discord.py
weather/          počasí z Open-Meteo, BEZ závislosti na discord.py
pubs/             hospody a hledání termínu pro /na-pivo, BEZ závislosti na discord.py
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
- Registrace commandů (`ObedBot.sync_commands`): při `GUILD_IDS` serverové kopie **bez kontextu** (na serveru
  beze změny) + globální sada **jen s kontextem DM s botem** (v DM fungují, na serveru nejsou dvakrát). Kontext se
  nastavuje na stromu až po synchronizaci serverů, protože serverová kopie a globální command jsou tentýž objekt.
  Hlídá to `tests/test_sync.py`. Kód commandů nesmí počítat s `interaction.guild` (v DM je `None`).

## Oprávnění a intenty – kontrola při každé změně

Aktuální stav (ověřeno pro verzi s `/ppv`, `/purkyne`, `/menzy`, `/restaurace`, `/mhd`, `/mhd-purkyne`, `/letaky`, `/maso`, `/napoje`, `/pivo`, `/domu`, `/obed`, `/na-pivo`, `/na-pivo-termin`, `/co-jist`, `/pocasi`, `/novinky`):

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
  Karta „Menu č. 3 – výběr pizzy“ (4 pizzy týdne s ingrediencemi) se načte do `Dish.options` a v `/restaurace`
  se vykreslí zvlášť přes celou šířku (`render.options_field`).

**Slevy a letáky – Kupi.cz** (`shops/`):
- Jen veřejné HTML stránky, které povoluje `robots.txt`: kategorie `/slevy/<kategorie>?page=N` a stránky poboček
  `/obchod/<řetězec>/<pobočka>`. **Nepoužívej** interní endpointy `/get-slevy`, `/get-letaky`, `/get-akce` …
  (robots.txt je zakazuje), řazení `?ord=` ani vícenásobné filtry obchodů.
- Stahuje se postupně s pauzou (`PAGE_DELAY`), na pozadí každou hodinu (`REFRESH_MINUTES`, `Shops.refresh_all`).
  Naparsované výsledky drží `Shops` v paměti, commandy je jen čtou. Nepřidávej stahování „na každé kliknutí“.
- Kategorie: řádek slevy (`div.discount_row`) = jedna akce v jednom obchodě. Nahoře bývají sponzorované produkty
  jiných řetězců, proto se akce **vždy filtrují podle názvu obchodu** (`Store.shop_labels`). Další stránka =
  odkaz přesně na `?page=N+1`.
- Albert má akce „Albert“, „Albert supermarket“ a „Albert hypermarket“. Albert Semilasso (Kosmova) je supermarket,
  hypermarketové akce se k němu nezapočítávají.
- Maso = čerstvé maso po podkategoriích (`MEAT_CATEGORIES`). Šunky, salámy, párky a ryby schválně ne, jsou jich stovky.
- Nápoje (`DRINK_CATEGORIES`: energetické + limonády) jen bez cukru (`shops.service.sugar_free`). Kupi.cz varianty
  často neuvádí („různé druhy“), proto dvě úrovně: `SUGAR_FREE` = název/poznámka říká zero/bez cukru/max…,
  `MAYBE_SUGAR_FREE` = „různé/vybrané druhy“ značky ze seznamu `ZERO_BRANDS`. Ostatní (např. „regular“) se nezobrazují.
- Pivo (`BEER_CATEGORIES`, `shops.service.beer_pack`): balení se pozná z balení akce (`Deal.amount`, např. „6x 0.5 l“)
  a poznámky („plech“, „+3 Kč záloha na láhev“ = lahev, „záloha na láhve“ = multipack). Název se zkracuje na značku
  (`beer_short_name`, slovník `BEER_BRANDS` – Velkopopovický Kozel → Kozel, Pilsner Urquell → Plzeň) + styl na konec. Vyřazené: PET, objem > 1 l (sudy),
  dárková balení (krýgl, sklenice, metr piv…) a cena nad 150 Kč/l. Řadí se podle slevy a pak ceny za litr (`Deal.unit_price`).
  **Uživatelům se ceny piva ukazují za 0,5 l** (`price_per_half_liter`), ne za litr – na půllitry jsou zvyklí.
  Multipack (`BEER_PACK`) má hlavní cenu za kus a celkovou v závorce. V 🏆 nejlevnějších se u lahve/plechovky 0,5 l
  „/0,5 l“ nepíše (je to jasné).
- Řádek akce: sleva vlevo ve stejně širokém `kódu` (doplněno mezerou U+2007, Discord ji neořízne), datum bez dne
  v týdnu, „📅 od …“ místo 🔜 (Discord ho kreslí jako nečitelnou šipku). Stejná akce (produkt, balení, cena) se
  slučuje. Obchody bez akcí se nevykreslují jako karta, jen se vyjmenují v hlavičce.
- Výpisy akcí se otevírají s „jen se slevou“ (`DEFAULT_ONLY_DISCOUNT`). Pozor: BILLA a Globus u piva slevu v % neuvádějí,
  takže tam pak bývá prázdno – je to záměr uživatele.
- Obchody se v akcích jmenují obecně („BILLA“, „Albert supermarket“, „Globus“), protože akce na Kupi.cz jsou za celý řetězec;
  pobočka je jen v řádku 📍 u letáků (letáky a otevírací doba jsou za pobočku).
- Výpisy akcí (`cogs/slevy.DEAL_VIEWS`) sdílí kód; nový výpis = `DealView` (kategorie Kupi, tlačítka filtru, funkce
  `classify` akce → klíč filtru / None, `loader` v `Shops`) + kategorie v `shops/service.py`.
  Tlačítka mají stav v custom_id `slevy:<pohled>:<filtr>:<jen se slevou 0/1>:<slot>`, příznak 0/1 je volitelný
  kvůli tlačítkům ze starších zpráv.
- Akce řetězců jsou většinou celostátní; letáky a otevírací doba jsou ze stránky konkrétní pobočky
  (BILLA Srbská má „malý leták“). Otevírací doba je v JSON-LD (`openingHours`).

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

**Počasí – Open-Meteo** (`weather/openmeteo.py`): zdarma bez klíče, data CC BY 4.0 → v embedu musí zůstat
uvedený zdroj („Data: Open-Meteo.com“). Souřadnice FITu, obnova na pozadí každých 15 min. Po 21:00 (do 4:00)
`window_advice` radí s otevřeným oknem podle předpovědi do 7:00 (mráz, déšť, chladno, vítr).

**/domu** (`cogs/mhd.py`, `Timetable.connections`): spoje z `HOME_ORIGINS` (Česká, Hlavní nádraží – z Malinovského
nám. se nejezdí) do `HOMES` (PPV, Purkyně), jen tramvaje (`HOME_ROUTE_TYPES`) a noční `HOME_NIGHT_LINES` (N99). Loader drží `trip_visits` = průjezdy sledovanými zastávkami včetně konečné.
Hledá se i přes půlnoc: služba včerejška (časy 24:xx), dnešní i zítřejší (0:xx), noc končí ve 4:00. Noční linky = `N…`.
Výpis je jedna společná karta: `all_home_trips` sloučí stejný spoj ke všem kolejím (`HomeTrip.arrivals`), takže
řádek je „odjezd · linka → Purkyně 22:53 · PPV 22:57“. Poslední denní spoj se hledá ke každým kolejím zvlášť.
Časy jsou z hlavní výchozí zastávky (`HOME_ORIGINS[0]` = Česká). O kolik dřív jede linka z Hlavního nádraží, se napíše
jednou nahoře (`origin_offsets` = nejčastější rozdíl z JŘ, u 12 je 6 min, u N99 3 min).

**/co-jist** (`cogs/cojist.py`): přepínač „Do 150 Kč“ (`MAX_PRICE`) je ve výchozím stavu vypnutý, jídlo bez ceny se nevyřazuje.
Tlačítka `cojist:<rozsah>:<r|s|c>:<limit 0/1>`, příznak limitu je volitelný kvůli tlačítkům ze starších zpráv (= vypnuto).

**/obed** (`cogs/obed.py`): stav hlasování (kdo, kam, v kolik) je **jen v embedu zprávy** – tlačítka ho přečtou
(`read_state`), upraví a přepíšou. Žádná databáze, přežije restart. Názvy polí musí odpovídat `SPOTS`.

**/na-pivo, /na-pivo-termin** (`cogs/napivo.py`, `pubs/`): stejně jako /obed je stav **jen v embedu zprávy**.
Datum založení je v `embed.timestamp` (z něj se dopočítá rok a 14 dní hlasování), den pozvánky v nadpisu.
- Podniky a oblasti jsou v `pubs/venues.py` (`AREAS`, `PUBS`). Nový podnik = řádek v `PUBS`; klíč se nemění
  (je hodnotou ve výběru), podnik se v embedu pozná podle názvu (`by_name`). Výběr „Kam“ má oblasti i podniky
  dohromady a **unese max. 25 možností** (hlídá test). Při překročení je potřeba dvoustupňový výběr (oblast → podnik).
- Mapa = Google Maps vyhledávání z názvu a adresy, `query` ho upřesní, `map_url` (odkaz ze „Sdílet“) má přednost.
  Adresy u Zach klubu, Mystiky, Utopie a Starověké krčmy nejsou ověřené (mapa je jen hledání podle názvu).
- /na-pivo: `napivo:cas` a `napivo:kam` jsou výběry (DynamicItem[Select]), `napivo:a:<jdu|jindy|nejdu>` odpovědi,
  `napivo:mapa` = 🗺️ Kde co je (ephemeral), `napivo:termin` = založí hledání termínu se stejným místem.
- /na-pivo-termin: den = tlačítko `pivokdy:d:<RRRRMMDD>` → okno (Modal se Select v Label) „od kolika“
  (❌ nemůžu / kdykoliv / od HH:00). Odeslání okna upraví původní zprávu (`response.edit_message` u modal submitu).
  Nejlepší den = nejvíc lidí, čas = nejpozdější „od“ (`pubs.planning.best_day`). `pivokdy:svolat` pošle pozvánku
  /na-pivo na nejlepší den a v textu zprávy označí (pingne) ty, kdo ten den můžou.

Obecně: na weby chodíme s cache (`lunch/fetcher.py`) a slušným User-Agentem, žádné agresivní dotazování.

**Obnova na pozadí (rychlost commandů):** každý cog má `tasks.loop`, který data pravidelně stáhne a naparsuje
(menzy 10 min a restaurace 30 min, výluky 5 min, Kupi.cz 60 min). Commandy tak jen čtou hotové výsledky
(desítky ms). Mimo `LUNCH_HOURS` se jídelníčky nestahují znovu: platí, co se dnes stáhlo, až do půlnoci
(`service.effective_ttl`), smyčka jen dotáhne, co v cache chybí (po restartu, po půlnoci). Pravidla:
- TTL cache musí být **delší** než interval obnovy, jinak by command stahoval sám.
- Parsování větších HTML/zipů patří do `asyncio.to_thread`, jinak se zasekne celý bot.
- Nová obnova na pozadí se spouští jen když `bot.background_refresh` (v testech `BACKGROUND_REFRESH=0`,
  aby testy nestahovaly z internetu).
- Při chybě obnovy se nechávají předchozí data (lepší starší výpis než žádný).
- Každá obnova na pozadí běží v `async with loading.track(self.bot, "<název>")` (`utils/loading.py`) a při startu
  smyčky se registruje `loading.expect(...)`; když se zdroj schválně nestahuje, volá `loading.skip(...)`.
  Tracker loguje „✅ Načteno: … za X s“ (po startu vždy, pak jen pomalé obnovy), jednou souhrn „🚀 Všechna data po startu
  načtena“ a při načítání delším než 2 s přidá na konec statusu bota „⏳“ (`ObedBot.update_presence`).

## Nasazení

- Push do `main` → GitHub Actions (`.github/workflows/ci.yml`): testy → build image →
  `ghcr.io/tenjakub/vut_monkes_bot:latest` + `:sha-<commit>`.
- Homelab (AlmaLinux, Portainer): `docker-compose.yml` = bot + Watchtower.
  Používáme fork **`nickfedor/watchtower`**, protože původní `containrrr/watchtower` je archivovaný a s novým Dockerem
  nefunguje. Watchtower má scope `vut-monkes-bot` a hlídá jen tenhle stack.
- SELinux: bot má named volume (`bot_data`), Watchtower má `security_opt: label=disable` kvůli `docker.sock`.
- Verze: číslo verze z `CHANGELOG.md` (`utils/changelog.py`) + `config.BOT_VERSION` = env `BOT_VERSION` (CI ho do image vloží jako krátký hash = tag `sha-…`),
  lokálně `dev <git hash>`. Zobrazuje se ve statusu bota, v logu při startu a v chybové hlášce (s odkazem na Issues).
- Bio bota = popis aplikace v Developer Portalu (nastavuje uživatel ručně, text je v README).
- Healthcheck: bot každých 30 s „dotkne“ `HEALTH_FILE`, jen když je připojený. `healthcheck.py` kontroluje stáří.
- Dva boti: **vývojový** (lokálně, testovací server) a **produkční** (Docker, hlavní server). Stejný kód,
  jiný token a `GUILD_IDS`.
- Nové runtime závislosti patří do `requirements.txt` (jinak je image nebude mít), testovací do `requirements-dev.txt`.
