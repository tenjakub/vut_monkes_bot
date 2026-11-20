# VUT Monkes bot

Discord bot v Pythonu ([discord.py](https://discordpy.readthedocs.io/) 2.x) pro jeden kamarádský
server. Vypisuje, co je dnes k obědu v menzách VUT a v okolních restauracích a kdy jede MHD.
Výpis je v embedech a pod ním jsou tlačítka na přepínání.

> [!NOTE]
> 🤖 **Tenhle projekt je psaný AI.** Celý kód, testy i tohle README napsal
> [Claude](https://www.anthropic.com/claude) (model od Anthropicu) v
> [Claude Code](https://claude.com/claude-code). Majitel repa zadává, co má bot umět,
> testuje ho na serveru a rozhoduje o směru, ale kód sám nepíše. Proto mají commity
> `Co-Authored-By: Claude`.
>
> Pokud tu najdeš chybu nebo podivné řešení, je to nejspíš chyba AI, ne člověka. 🙂
>
> Pokyny a kontext pro AI agenty (architektura, záludnosti zdrojů dat, oprávnění bota) jsou
> v [AGENTS.md](AGENTS.md). [CLAUDE.md](CLAUDE.md) na něj jen odkazuje.

## Commandy

| Command | Co dělá |
|---|---|
| `/ppv` | Economy: Menza Kolejní, Pizzerie Mozzarella, Menza Starý pivovar |
| `/purkyne` | Economy: Menza Purkyňova + Starý pivovar |
| `/menzy` | Economy ze všech menz, kde ho vaří (Kolejní, Mozzarella, SP, Purkyňova, Q Technická, FCH, Rybkova) |
| `/restaurace` | Polední menu: U 3 opic, Padagali, La Strada, U Karla, Portoriko |
| `/mhd` | PPV (koleje Pod Palackého vrchem): odjezdy z Technologického parku (tramvaje) a z Kolejní + výluky na těch linkách |
| `/mhd-purkyne` | Totéž u kolejí Purkyňova: Červinkova (tramvaje) a Skácelova (autobusy a trolejbusy zvlášť na východ a na západ) |

Všechny tři menzové commandy mají volitelný parametr `vse: True`. Ten místo Economy ukáže
polévky a všechna hlavní jídla (saláty, přílohy a dezerty vynechá).

Tlačítka pod zprávou přepínají skupinu menz, Economy/vše a obnovují data. Stav je uložený
přímo v ID tlačítka, takže tlačítka fungují i po restartu bota.

Každé jídlo je ve výpisu jako kartička: emoji, štítek (`E1`…), cena a název. Kartičky se na desktopu
skládají do mřížky po třech, polévky jsou nahoře přes celou šířku.
Čas stažení dat je v hlavičce zprávy jako Discord timestamp (každý ho vidí ve svém čase
a relativní „před X minutami“ se průběžně aktualizuje).
Emoji se vybírá podle klíčových slov v názvu jídla, pravidla jsou v `lunch/emoji.py`
(stačí připsat řádek s emoji a regexem).

### /mhd

Odjezdy na hodinu dopředu v kartičkách. Časy jsou Discord timestampy („in 5 minutes“ se samo
odpočítává). Tlačítky se přepíná mezi oblastmi (Technopark + Kolejní / Koleje Purkyňova)
a jednotlivými zastávkami. Každá zastávka má vlastní způsob zobrazení:

| Zastávka | Zobrazení |
|---|---|
| Technologický park, Červinkova | jen tramvaje, **jedna kartička na směr**: „🚋 Tram → Centrum“ / „🚋 Tram → Technologický park“, u každého času číslo linky (`12`, `10`, `4`). |
| Kolejní | **72 → Semilasso** (spoje, které z Technoparku jedou dál) je vždy první. **65** má jednu kartičku bez ohledu na cíl. Končící 72 jsou nevýrazně na konci („🛑 dál nejede“). |
| Skácelova → východ / západ | autobusy a trolejbusy, rozdělené podle nástupiště: **východ** (další zastávka Slovanské náměstí) a **západ** (Záhřebská). Kartička pro každou linku, seřazené podle čísla linky. V nadpisu je obvyklá konečná, jiná konečná je jen značka za časem. |

Všechno se nastavuje v `BOARDS` a `AREAS` v `transit/service.py` (zastávka, případně jen některá nástupiště,
typy vozidel, způsob zobrazení `layout`, popisky směrů, sloučené linky, popisek směru u pokračujících spojů).

Odjezdy jsou **podle jízdního řádu, bez zpoždění**. Realtime feed KORDIS sice obsahuje polohy
vozidel, ale nemá zpoždění a jeho ID spojů zatím nesedí na jízdní řád. Výluky z něj ale bot bere.

Ceny u menz jsou pro **studenty VUT** (1. cena na webu KaM). Změníš je v `lunch/kam.py`
(`PRICE_CLASS` / `PRICE_LABEL`).

## Zdroje dat

- **Menzy:** `https://www.kam.vut.cz/?p=menu&provoz=<ID>`. ID provozů najdeš na
  [přehledu KaM](https://www.kam.vut.cz/?p=otdo). Economy jídla se poznají podle prefixu `Economy N:`.
- **U 3 opic** (ID 3225), **Padagali** (ID 4116, Kotlářská), **U Karla** (ID 6695) a **Portoriko**
  (ID 8467, Srbská): [menicka.cz](https://www.menicka.cz)
- **La Strada** (Kounicova): [lastrada-brno.cz/poledni-menu](https://lastrada-brno.cz/poledni-menu/).
  Na menicka.cz není, takže má vlastní scraper.

- **MHD:** otevřená data KORDIS JMK (licence CC BY) – jízdní řád ve formátu GTFS
  (`kordis-jmk.cz/gtfs/gtfs.zip`, ukládá se do `data/` a obnovuje každých 12 h) a výluky
  z GTFS Realtime (`kordis-jmk.cz/gtfs/gtfsReal.dat`, cache 5 min).

Stažené stránky se cachují (menzy 5 min, restaurace 30 min). Tlačítko „Obnovit“ stáhne data znovu,
nejvýš jednou za minutu.

## Discord aplikace

Postup je stejný pro vývojového i produkčního bota, jen se udělá dvakrát (každý bot = vlastní aplikace).

### 1. Založení a nastavení aplikace

Na <https://discord.com/developers/applications> → **New Application**. Pak nastav:

| Záložka | Nastavení |
|---|---|
| **Bot** | **Reset Token** → token do `.env` / Portaineru (ukáže se jen jednou, nikomu ho neposílej) |
| **Bot** | **Public Bot**: vypnout (pozvat ho pak můžeš jen ty) |
| **Bot** | **Requires OAuth2 Code Grant**: vypnout |
| **Bot** | **Privileged Gateway Intents** (Presence, Server Members, Message Content): **všechny vypnout**. Bot používá jen slash commandy a tlačítka, nic z toho nepotřebuje. |
| **Installation** | **Installation Contexts**: jen **Guild Install** (User Install vypnout) |
| **Installation** | **Install Link**: *None* (pozývá se odkazem níže) |

### 2. Oprávnění

Bot potřebuje jen základní oprávnění:

- **View Channels**: vidět kanál, kde se command použil
- **Send Messages**: odpovídat
- **Embed Links**: kartičky s jídly a odjezdy jsou embedy

Nic dalšího (správa zpráv, rolí, administrátor apod.) nedávej. Číselně je to `19456`.

### 3. Pozvání na server

Pozvánka nezávisí na tom, kde bot běží. Vývojového bota, který běží lokálně, pozveš úplně stejně
jako produkčního, jen jeho vlastním odkazem na testovací server.

1. Zkopíruj **Application ID** (záložka **General Information**).
2. Otevři v prohlížeči tenhle odkaz, místo `APP_ID` dej to číslo:

   ```
   https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot+applications.commands&permissions=19456&integration_type=0
   ```

   Případně si stejný odkaz naklikej v **OAuth2 → URL Generator**: scopes `bot` + `applications.commands`,
   oprávnění ze seznamu výše, Integration Type *Guild Install*.
3. Vyber server a potvrď. Musíš na něm mít oprávnění **Spravovat server**.
4. ID serveru (pravý klik na server → **Kopírovat ID serveru**, potřebuje zapnutý *Režim vývojáře*
   v Nastavení → Pokročilé) dej do `GUILD_IDS`.
5. Spusť bota (lokálně `python bot.py`, na serveru redeploy stacku). Commandy se na serveru objeví hned.

Kdo smí které commandy používat a ve kterých kanálech, se dá na serveru omezit v
**Nastavení serveru → Integrace → (bot)**.

### Vývojový a produkční bot

Používají se dvě samostatné aplikace v Developer Portalu. Kód je stejný, liší se jen token a server:

| | Vývojový bot | Produkční bot |
|---|---|---|
| kde běží | lokálně (`python bot.py`) | homelab, Docker z `main` |
| token a server | `.env` ve složce projektu | proměnné stacku v Portaineru |
| `GUILD_IDS` | ID testovacího serveru | ID vašeho serveru |

Díky tomu se dá zkoušet nová verze na testovacím serveru, zatímco na hlavním serveru běží ta stabilní.
Tlačítka pod zprávami patří vždy botovi, který zprávu poslal, takže se instance nepletou.
Jen nikdy nespouštěj dvě instance se **stejným** tokenem, jinak by na commandy odpovídaly obě.

Když je vyplněné `GUILD_IDS`, bot zaregistruje commandy jen na těch serverech (hned) a případné
staré globální commandy smaže, aby se v nabídce neukazovaly dvakrát.

### Jméno, profilovka a banner

Úpravy v Developer Portalu (záložka **Bot** → Username, Icon, Banner) se projeví hned, bota není
potřeba restartovat ani znovu nasazovat. Discord klient si ale obrázky cachuje, takže je někdy uvidíš
až po `Ctrl+R`. Jméno jde měnit jen párkrát za hodinu. Pokud má bot na serveru nastavenou přezdívku,
zobrazuje se místo jména ta (Nastavení serveru → Členové). Název a ikona v **General Information**
patří aplikaci. Ty jsou vidět u slash commandů a v profilu aplikace.

## Nasazení (Docker, homelab)

Jak to funguje: každý push do `main` spustí [GitHub Actions](.github/workflows/ci.yml). Ty pustí testy
a když projdou, sestaví Docker image a nahrají ho do GitHub Container Registry jako
`ghcr.io/tenjakub/vut_monkes_bot:latest` (a navíc `:sha-<commit>`). Na serveru běží vedle bota
[Watchtower](https://watchtower.nickfedor.com/), který každých 5 minut zkontroluje, jestli je nový image,
a když ano, bota sám restartuje s novou verzí. Na serveru se nic nesestavuje a nic se neotevírá ven.

### Portainer

1. **Stacks → Add stack**, pojmenuj ho třeba `vut-monkes-bot`.
2. Build method **Repository**: URL `https://github.com/tenjakub/vut_monkes_bot`, reference
   `refs/heads/main`, compose path `docker-compose.yml`. (Nebo **Web editor** a vlož obsah
   [docker-compose.yml](docker-compose.yml).)
3. **Environment variables**: `DISCORD_TOKEN` a ideálně `GUILD_IDS`. Volitelně `BOT_TAG`
   a `WATCHTOWER_POLL_INTERVAL` (viz [.env.example](.env.example)).
4. **Deploy the stack**. Nastartují dva kontejnery: `vut-monkes-bot` a `vut-monkes-watchtower`.

### Bez Portaineru

Na serveru stačí složka s `docker-compose.yml` a `.env` (podle `.env.example`):

```bash
docker compose up -d
```

### Aktualizace a návrat ke starší verzi

- **Automaticky:** do ~5 minut po zeleném CI na GitHubu.
- **Hned:** v Portaineru u stacku **Pull and redeploy**, nebo `docker compose pull && docker compose up -d`.
- **Návrat zpět:** nastav `BOT_TAG` na konkrétní verzi, např. `sha-fbc4bee`
  ([seznam verzí](https://github.com/tenjakub/vut_monkes_bot/pkgs/container/vut_monkes_bot)),
  a redeployni. Dokud je tam konkrétní tag, Watchtower bota nemění. Pro návrat k automatice dej zpět `latest`.
- Jakou verzi bot právě běží, je vidět v logu hned na začátku (`Startuje VUT Monkes bot, verze …`).

### Logy a stav

- Portainer → kontejner `vut-monkes-bot` → **Logs**, nebo `docker logs -f vut-monkes-bot`.
- Kontejner má healthcheck. „healthy“ znamená, že je bot opravdu připojený k Discordu, nejen že proces běží.
- Stažený jízdní řád MHD je ve volume `bot_data`, takže přežije restart i update.

### Poznámky k AlmaLinuxu (SELinux)

- Bot používá named volume, takže nic se SELinuxem řešit nemusí.
- Watchtower potřebuje přístup k `/var/run/docker.sock`. Kvůli SELinuxu má v compose `security_opt: label=disable`,
  jinak by ho SELinux zablokoval.

### Lokální sestavení image (test před pushem)

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up --build bot
```

## Spuštění lokálně bez Dockeru (vývoj)

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Do `.env` vyplň `DISCORD_TOKEN`. Do `GUILD_IDS` doporučuju dát ID vašeho serveru,
pak se commandy objeví hned. Bez něj se registrují globálně, což může trvat až hodinu.

```bash
.venv/bin/python bot.py
```

## Struktura

```
bot.py              # vstupní bod, načte cogy, synchronizuje slash commandy, heartbeat
config.py           # načtení .env
healthcheck.py      # Docker healthcheck (je bot připojený?)
Dockerfile          # image bota
docker-compose.yml  # nasazení: bot + Watchtower (automatické aktualizace)
docker-compose.build.yml  # lokální sestavení image místo stažení z GHCR
.github/workflows/  # CI: testy + build a push image do GHCR
cogs/menza.py       # /ppv, /purkyne, /menzy + tlačítka
cogs/restaurace.py  # /restaurace + tlačítko obnovit
cogs/mhd.py         # /mhd, /mhd-purkyne + tlačítka
lunch/              # stahování a parsování (bez závislosti na Discordu)
  kam.py            #   menzy VUT – seznam menz a skupin (ppv, purkyne, vse)
  emoji.py          #   výběr emoji k jídlu podle klíčových slov
  menicka.py        #   menicka.cz
  lastrada.py       #   La Strada
  service.py        #   seznam restaurací, paralelní načítání
  fetcher.py        #   HTTP + cache
transit/            # MHD (bez závislosti na Discordu)
  gtfs.py           #   načtení jízdního řádu, odjezdy, navazující spoje
  alerts.py         #   výluky z GTFS Realtime
  service.py        #   zastávky (BOARDS), stahování a obnova dat
utils/render.py     # převod na Discord embedy (limity délky apod.)
tests/              # testy parserů, emoji, vykreslování a MHD
AGENTS.md           # kontext a pravidla pro AI agenty (CLAUDE.md na něj odkazuje)
```

**Přidání restaurace z menicka.cz:** najdi její ID v URL (`menicka.cz/1234-nazev.html`)
a přidej položku do `RESTAURANTS` v `lunch/service.py`.

**Přidání menzy nebo skupiny:** uprav `MENZY` / `GROUPS` v `lunch/kam.py`. Popisek tlačítka
pro novou skupinu přidej do `GROUP_BUTTONS` v `cogs/menza.py` a případně k ní přidej command.

## Testy

```bash
.venv/bin/pip install -r requirements-dev.txt
```

```bash
.venv/bin/python -m pytest
```
