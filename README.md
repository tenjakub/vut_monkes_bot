# Obědový Discord bot

Discord bot v Pythonu ([discord.py](https://discordpy.readthedocs.io/) 2.x), který vypisuje,
co je dnes k obědu v menzách VUT a v okolních restauracích. Výpis je v embedech
a pod ním jsou tlačítka na přepínání.

## Commandy

| Command | Co dělá |
|---|---|
| `/menza` | Economy menu: Menza Kolejní, Pizzerie Mozzarella, Menza Starý pivovar (`kde: ppv`, výchozí) |
| `/menza kde: purkyne` | Menza Purkyňova + Starý pivovar |
| `/menza kde: vse` | Všechny menzy, kde bývá Economy (Kolejní, Mozzarella, SP, Purkyňova, Q Technická, FCH, Rybkova) |
| `/menza vse_jidla: True` | Místo jen Economy ukáže polévky a všechna hlavní jídla (saláty, přílohy a dezerty vynechá) |
| `/restaurace` | Polední menu: U 3 opic, Padagali, La Strada |

Tlačítka pod zprávou přepínají skupinu menz, Economy/vše a obnovují data. Stav je uložený
přímo v ID tlačítka, takže tlačítka fungují i po restartu bota.

Ceny u menz jsou pro **studenty VUT** (1. cena na webu KaM). Změníš je v `lunch/kam.py`
(`PRICE_CLASS` / `PRICE_LABEL`).

## Zdroje dat

- **Menzy:** `https://www.kam.vut.cz/?p=menu&provoz=<ID>`. ID provozů najdeš na
  [přehledu KaM](https://www.kam.vut.cz/?p=otdo). Economy jídla se poznají podle prefixu `Economy N:`.
- **U 3 opic** (ID 3225) a **Padagali** (ID 4116, Kotlářská): [menicka.cz](https://www.menicka.cz)
- **La Strada** (Kounicova): [lastrada-brno.cz/poledni-menu](https://lastrada-brno.cz/poledni-menu/).
  Na menicka.cz není, takže má vlastní scraper.

Stažené stránky se cachují (menzy 5 min, restaurace 30 min). Tlačítko „Obnovit“ stáhne data znovu,
nejvýš jednou za minutu.

## Spuštění

1. Na <https://discord.com/developers/applications> vytvoř aplikaci, v záložce **Bot** vygeneruj token.
2. V **OAuth2 → URL Generator** zaškrtni scopes `bot` + `applications.commands`
   a permissions `Send Messages`, `Embed Links`. Vygenerovaným odkazem pozvi bota na server.
3. Nainstaluj a spusť:

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
bot.py              # vstupní bod, načte cogy, synchronizuje slash commandy
config.py           # načtení .env
cogs/menza.py       # /menza + tlačítka
cogs/restaurace.py  # /restaurace + tlačítko obnovit
lunch/              # stahování a parsování (bez závislosti na Discordu)
  kam.py            #   menzy VUT – seznam menz a skupin (ppv, purkyne, vse)
  menicka.py        #   menicka.cz
  lastrada.py       #   La Strada
  service.py        #   seznam restaurací, paralelní načítání
  fetcher.py        #   HTTP + cache
utils/render.py     # převod na Discord embedy (limity délky apod.)
tests/              # testy parserů nad uloženými HTML stránkami
```

**Přidání restaurace z menicka.cz:** najdi její ID v URL (`menicka.cz/1234-nazev.html`)
a přidej položku do `RESTAURANTS` v `lunch/service.py`.

**Přidání menzy nebo skupiny:** uprav `MENZY` / `GROUPS` v `lunch/kam.py`. Popisek tlačítka
pro novou skupinu přidej do `GROUP_BUTTONS` v `cogs/menza.py`.

## Testy

```bash
.venv/bin/pip install -r requirements-dev.txt
```

```bash
.venv/bin/python -m pytest
```
