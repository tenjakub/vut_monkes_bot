# VUT Monkes bot

Discord bot pro kamarádský server studentů VUT. Ukáže, co je dnes k obědu v menzách a okolních
restauracích, kdy jede MHD, co je v akci v supermarketech a jaké bude počasí. Umí i svolat
společný oběd. Napsaný v Pythonu ([discord.py](https://discordpy.readthedocs.io/) 2.x), výpisy jsou
v embedech s tlačítky na přepínání.

> [!NOTE]
> 🤖 **Tenhle projekt je psaný AI.** Celý kód, testy i tohle README napsal
> [Claude](https://www.anthropic.com/claude) v [Claude Code](https://claude.com/claude-code).
> Majitel repa zadává, co má bot umět, testuje ho na serveru a rozhoduje, ale kód sám nepíše.
> Proto mají commity `Co-Authored-By: Claude`. Najdeš-li chybu nebo podivné řešení, je to nejspíš chyba AI. 🙂
>
> Kontext a pravidla pro AI agenty jsou v [AGENTS.md](AGENTS.md) ([CLAUDE.md](CLAUDE.md) na něj jen odkazuje).

## Commandy

| Command | Co dělá |
|---|---|
| `/ppv` | Economy obědy: Menza Kolejní, Pizzerie Mozzarella, Menza Starý pivovar |
| `/purkyne` | Economy obědy: Menza Purkyňova + Starý pivovar |
| `/menzy` | Economy ze všech menz, kde ho vaří |
| `/restaurace` | Polední menu: U 3 opic, Padagali, La Strada, U Karla, Portoriko, Sesamo |
| `/mhd` | Odjezdy u kolejí PPV (Technologický park, Kolejní) + výluky |
| `/mhd-purkyne` | Odjezdy u Purkyňových kolejí (Červinkova, Skácelova) + výluky |
| `/kola` | Volná sdílená kola nextbike na stanicích u PPV (tlačítky i u Purkyní a FITu) |
| `/domu` | Jak se dostat z centra (Česká, Hlavní nádraží) na koleje: tramvaje, poslední denní spoj, noční N99 |
| `/letaky` | Akční letáky a otevírací doba okolních Lidlů, BILLY, Alberta a Globusu |
| `/maso` | Slevy na čerstvé maso, nahoře 🏆 nejlevnější za kilo |
| `/pivo` | Pivo v akci (lahve, plechovky, multipacky), ceny za půllitr nebo za kus, 🔥 nejlevnější / 🎣 sleva na oko |
| `/napoje` | Energetické nápoje a limonády bez cukru v akci |
| `/obed` | Hlasování „Kdo jde na oběd?“: kam a v kolik |
| `/na-pivo` | Pozvánka na dnešní pivo: v kolik, kam (s mapou) a kdo jde / nejde / šel by jindy |
| `/na-pivo-termin` | Hledání společného dne na pivo v příštích dvou týdnech i s počasím, nejlepší termín jde rovnou svolat |
| `/co-jist` | Náhodné jídlo z dnešních menz a restaurací, volitelně do 150 Kč |
| `/pocasi` | Počasí u FITu: teď, dalších 18 h, dnes a zítra, rady k oblečení a k oknu přes noc, kdo má svátek |
| `/otevreno` | Co má teď otevřeno: menzy, pizzerie, kavárny a bufety VUT a okolní obchody (i se svátky) |
| `/statistiky` | Které commandy se používají nejvíc (za 7 dní, 30 dní, od začátku) |
| `/hlidat` | Hlídání akcí: když bude v akci, co chceš (případně do zadané ceny), bot ti napíše do soukromé zprávy |
| `/novinky` | Co je nového (z [CHANGELOG.md](CHANGELOG.md)) |

Menzové commandy mají parametr `vse: True`: místo Economy ukážou polévky a všechna hlavní jídla.
Pod menzami a restauracemi je ⭐ **Ohodnotit** (👍 dobré / 😐 neurazí / 👎 špatné), souhrn je pak vidět pod jídlem.
Tlačítka pod zprávou mají stav uložený přímo v ID, takže fungují i po restartu bota.
Commandy fungují i v soukromém chatu s botem.

## Zdroje dat

Data se stahují a parsují průběžně na pozadí, commandy jen sáhnou do hotových výsledků v paměti.
Tlačítko 🔄 Obnovit stáhne data hned (stejnou stránku nejvýš jednou za minutu).

| Zdroj | Odkud | Obnova na pozadí |
|---|---|---|
| Menzy | [KaM VUT](https://www.kam.vut.cz/?p=otdo) (ceny pro studenty VUT, otevírací doby) | 10 min, 6–20 h |
| Restaurace | [menicka.cz](https://www.menicka.cz), La Strada, U Karla a Sesamo z vlastních webů ([La Strada](https://lastrada-brno.cz/poledni-menu/), [U Karla](https://ukarlabrno.cz/menu/pages/poledni-menu), [Sesamo](https://sesamobrno.cz/#menu)) | 30 min, 6–20 h |
| MHD | otevřená data [KORDIS JMK](https://kordis-jmk.cz) (CC BY): jízdní řád GTFS a výluky z GTFS Realtime | jízdní řád po 12 h, výluky 5 min |
| Slevy a letáky | [Kupi.cz](https://www.kupi.cz), jen veřejné stránky povolené v `robots.txt` | 1 h |
| Kola | [nextbike Brno](https://nextbikeczech.com/mesto/brno/), otevřený GBFS feed (CC0) | 3 min |
| Počasí | [Open-Meteo](https://open-meteo.com) (CC BY 4.0) | 15 min |

Mimo 6–20 h platí jídelníčky stažené ten den až do půlnoci. MHD je **podle jízdního řádu, bez zpoždění**:
realtime feed KORDIS zpoždění neobsahuje.

## Discord aplikace

Vývojový a produkční bot jsou dvě samostatné aplikace v Developer Portalu. Kód mají stejný, liší se
token a `GUILD_IDS`. Postup níže se proto dělá pro každého zvlášť.

| | Vývojový bot | Produkční bot |
|---|---|---|
| kde běží | lokálně (`python bot.py`) | homelab, Docker z `main` |
| token a server | `.env` ve složce projektu | proměnné stacku v Portaineru |
| `GUILD_IDS` | ID testovacího serveru | ID hlavního serveru |

Nikdy nespouštěj dvě instance se **stejným** tokenem, jinak na commandy odpovídají obě.

### 1. Nastavení aplikace

Na <https://discord.com/developers/applications> → **New Application**:

| Záložka | Nastavení |
|---|---|
| **Bot** | **Reset Token** → token do `.env` / Portaineru (ukáže se jen jednou, nikomu ho neposílej) |
| **Bot** | **Public Bot** a **Requires OAuth2 Code Grant**: vypnout |
| **Bot** | **Privileged Gateway Intents**: všechny vypnout (bot používá jen slash commandy a tlačítka) |
| **Installation** | jen **Guild Install**, Install Link *None* |

### 2. Oprávnění

**View Channels**, **Send Messages**, **Embed Links** a **Create Events**, číselně `17592186063872`. Nic dalšího nedávej.

Create Events (Vytvářet události) potřebuje `/na-pivo`: když jdou aspoň 3 lidi, bot založí na serveru událost
a při změně času nebo místa ji upraví. Bez tohoto oprávnění funguje všechno ostatní, jen se událost nezaloží.
Už pozvanému botovi ho stačí přidat v **Nastavení serveru → Role → role bota**, nebo bota pozvat znovu odkazem níž.

### 3. Pozvání na server

Do odkazu dosaď **Application ID** (záložka **General Information**) a otevři ho v prohlížeči:

```
https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot+applications.commands&permissions=17592186063872&integration_type=0
```

Vyber server (potřebuješ na něm oprávnění **Spravovat server**). Jeho ID (pravý klik na server → **Kopírovat ID
serveru**, potřebuje zapnutý *Režim vývojáře*) dej do `GUILD_IDS`, víc serverů odděl čárkou. Pak se commandy objeví
hned. Kdo smí které commandy používat, se nastavuje v **Nastavení serveru → Integrace**.

### Profil bota

- **Jméno, profilovka, banner:** záložka **Bot**, projeví se hned (klient obrázky cachuje, případně `Ctrl+R`).
- **Status:** bot si ho nastavuje sám: `verze <číslo> · <hash>` (číslo z CHANGELOG.md, hash commitu = tag image
  `sha-<hash>`, lokálně `dev <hash>`).
- **Bio (About Me):** **General Information → Description** (max 400 znaků). Návrh:

  ```
  🐒 Bot pro VUT Monkes – obědy, MHD, slevy a počasí.

  🍽️ /ppv · /purkyne · /menzy · /restaurace · /co-jist · /obed
  🍺 /na-pivo · /na-pivo-termin
  🚏 /mhd · /mhd-purkyne · /domu · 🚲 /kola
  🛒 /letaky · /maso · /pivo · /napoje
  ☀️ /pocasi · 🕐 /otevreno · 📊 /statistiky · 📰 /novinky

  🐛 Něco nefunguje nebo máš nápad? https://github.com/tenjakub/vut_monkes_bot/issues
  ```

## Nasazení (Docker, homelab)

Každý push spustí [GitHub Actions](.github/workflows/ci.yml) s testy. Push do `main` navíc sestaví image
`ghcr.io/tenjakub/vut_monkes_bot:latest` (a `:sha-<commit>`). Na serveru vedle bota běží
[Watchtower](https://watchtower.nickfedor.com/), který každých 5 minut hledá nový image a bota sám aktualizuje.
Na serveru se nic nesestavuje a nic se neotevírá ven.

**Portainer:** **Stacks → Add stack** → Repository `https://github.com/tenjakub/vut_monkes_bot`, reference
`refs/heads/main`, compose path `docker-compose.yml`. Do **Environment variables** dej `DISCORD_TOKEN` a `GUILD_IDS`,
volitelně `BOT_TAG` a `WATCHTOWER_POLL_INTERVAL` (viz [.env.example](.env.example)). Bez Portaineru stačí
`docker-compose.yml` + `.env` a `docker compose up -d`.

- **Aktualizace hned:** v Portaineru **Pull and redeploy**, nebo `docker compose pull && docker compose up -d`.
- **Návrat ke starší verzi:** `BOT_TAG` nastav na konkrétní verzi, např. `sha-fbc4bee`
  ([seznam](https://github.com/tenjakub/vut_monkes_bot/pkgs/container/vut_monkes_bot)), a redeployni.
  Pro návrat k automatice dej zpět `latest`.
- **Logy:** `docker logs -f vut-monkes-bot`. Healthcheck „healthy“ znamená, že je bot opravdu připojený k Discordu.
- **AlmaLinux (SELinux):** bot má named volume `bot_data` (jízdní řád MHD a databáze), Watchtower kvůli `docker.sock`
  `security_opt: label=disable`.
- **Lokální build image:** `docker compose -f docker-compose.yml -f docker-compose.build.yml up --build bot`

### Databáze (SQLite)

Bot si data ukládá do jednoho souboru **`data/bot.db`** (SQLite). Žádný další kontejner ani databázový server:
v Dockeru je `data/` volume `bot_data`, takže databáze přežije aktualizaci i restart. **V Portaineru se nic
nastavuje**, stack zůstává stejný. Bot si databázi při startu sám vytvoří a doplní do ní nové tabulky (migrace).

Co se ukládá:

- **statistiky commandů** (`command_usage`): jen počty použití po dnech, ne kdo,
- **historie jídel** (`dish`): polévky a hlavní jídla z menz a restaurací po dnech s cenou (podklad pro statistiky,
  ~100 řádků denně),
- **hodnocení jídel** (`dish_rating`): 👍/😐/👎 s ID člověka (každý hodnotí jednou a může hodnocení zrušit).
- **ceny akcí** (`deal_price`): každá akce z Kupi.cz jednou (cena, sleva, platnost) pro 🔥/🎣 u slev a statistiky.
- **hlídání akcí** (`watch`, `watch_hit`): co kdo hlídá (s ID člověka, komu psát) a o kterých akcích už ví. Zruší se v `/hlidat`.

- **Zálohy:** bot jednou denně uloží kopii do `data/backups/bot-RRRR-MM-DD.db` a nechává posledních 7.
  Jsou ve stejném volume, takže chrání před chybou v botovi, ne před odchodem disku. Kopie mimo server:
  `docker cp vut-monkes-bot:/app/data/backups ./zalohy-bota`.
- **Nahlédnutí:** v Portaineru **Containers → vut-monkes-bot → Console → Connect** (`/bin/sh`) a pak
  `python -m storage` (tabulky a počty řádků) nebo `python -m storage "SELECT * FROM command_usage LIMIT 20"`.
  Databáze se tím otevře jen pro čtení. Na hezčí prohlížení stáhni soubor (`docker cp vut-monkes-bot:/app/data/bot.db .`)
  a otevři ho v [DB Browser for SQLite](https://sqlitebrowser.org/).
- **Obnova ze zálohy:** zastav stack, zálohu nakopíruj do volume jako `bot.db` (a smaž `bot.db-wal` a `bot.db-shm`,
  jestli tam jsou), spusť stack. Volume je na serveru v `/var/lib/docker/volumes/<název stacku>_bot_data/_data/`.
- **Návrat ke starší verzi** (`BOT_TAG`) s databází funguje: změny schématu jsou jen přidávací, starší bot
  nové tabulky prostě nepoužívá.

## Vývoj

Lokálně se vyvíjí přímo v Pythonu (3.14), Docker je jen pro produkci.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cp .env.example .env
```

Do `.env` vyplň `DISCORD_TOKEN` a `GUILD_IDS` vývojového bota.

Lokální bot má vlastní databázi `data/bot.db` (vytvoří se sama a do gitu nejde), produkční data tak nikdy
nepřepíše. Smazáním souboru začneš s prázdnou databází. Jinou cestu jde nastavit přes `DB_PATH` v `.env`.
Testy používají databázi v paměti.

```bash
.venv/bin/python bot.py
```

```bash
.venv/bin/python -m pytest -q
```

Testy jsou offline (uložené stránky v `tests/fixtures/`).

```
bot.py           # vstupní bod: cogy, registrace commandů, status, healthcheck
cogs/            # Discord vrstva: commandy, embedy, tlačítka
lunch/           # menzy a restaurace (stahování, parsování, emoji k jídlům)
transit/         # MHD: jízdní řád GTFS, výluky, zastávky
shops/           # slevy a letáky z Kupi.cz
weather/         # počasí z Open-Meteo
pubs/            # hospody pro /na-pivo a hledání termínu
utils/           # vykreslování embedů, changelog, načítání na pozadí
tests/           # testy
```

**Nová restaurace z menicka.cz:** ID z URL (`menicka.cz/1234-nazev.html`) a řádek v `RESTAURANTS`
v `lunch/service.py`. **Nová menza nebo skupina:** `MENZY` / `GROUPS` v `lunch/kam.py`, tlačítko v `GROUP_BUTTONS`
v `cogs/menza.py`. **Obchody a pobočky:** `STORES` v `shops/service.py`. **Zastávky MHD:** `BOARDS` a `AREAS`
v `transit/service.py`. **Nová hospoda pro /na-pivo:** řádek v `PUBS` v `pubs/venues.py` (název, oblast, adresa),
odkaz na mapu se složí sám. Volitelně i cena točeného (`beer`), zobrazí se po zapnutí `SHOW_BEER_PRICES`.

## Licence

Kód je pod licencí [MIT](LICENSE). Data, která bot zobrazuje, patří jejich zdrojům (KaM VUT, menicka.cz,
restaurace, Kupi.cz). Jízdní řády KORDIS JMK a počasí z Open-Meteo jsou pod licencí CC BY, s uvedením zdroje. Data o kolech nextbike jsou pod CC0.
