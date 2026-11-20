# Novinky

Co je nového ve VUT Monkes botovi. Píše se sem jen to, co poznají uživatelé na Discordu.
V Discordu to samé vypíše `/novinky`.

<!--
Formát (bot ho čte, viz utils/changelog.py):
## <verze> · <RRRR-MM-DD> · <krátký název>
- odrážky pro uživatele, česky, klidně s emoji
### Podnadpis (volitelný, v Discordu tučně)
Nejnovější verze je vždy nahoře.
-->

## 1.8 · 2026-11-20 · Oběd do 150 Kč 💸

- 💸 `/co-jist` má tlačítko **💸 Do 150 Kč**, se kterým losuje jen jídla do 150 Kč.
- 🌙 `/domu` ukazuje časy ze zastávky Česká a jen jednou napíše, o kolik minut dřív jede linka z Hlavního nádraží (12 o 6 min, N99 o 3 min).
- ⚡ `/co-jist`, menzy a restaurace odpovídají hned i večer. Dřív si v tu dobu jídelníčky stahovaly znovu.

## 1.7 · 2026-11-20 · Pro kolej

- 🍽️ Nový command `/obed` založí hlasování „Kdo jde na oběd?“. Každý klikne, do které menzy nebo restaurace jde a v kolik (nebo „🚶 Jdu teď“), a ve zprávě je hned vidět, kdo jde kam. Hlasování jde svolat i tlačítkem **Svolat oběd** přímo pod menzami a restauracemi.
- 🌙 Nový command `/domu` ukáže, jak se dostat z České nebo Hlavního nádraží na koleje: nejbližší tramvaje s časem příjezdu na Purkyňovy koleje i na PPV, poslední denní spoj a noční N99.
- ☀️ Nový command `/pocasi` ukáže počasí u FITu a kolejí: teď, dalších 18 hodin po třech hodinách, dnes a zítra, a poradí, jestli vzít deštník nebo bundu. Večer navíc poradí, jestli nechat přes noc otevřené okno.
- 🎲 Nový command `/co-jist` náhodně vybere jídlo z dnešních menz a restaurací. Tlačítkem se dá losovat znovu nebo jen z menz, jen Economy či jen z restaurací.
- 🏆 `/maso` a `/pivo` ukazují nahoře nejlevnější kus z každého druhu napříč obchody: maso podle ceny za kilo, pivo za půllitr.
- 🍺 U piva se ceny přepočítávají na půllitr místo litru. U multipacků je hlavní cena za kus a celková cena v závorce.
- ⏳ Když si bot zrovna déle načítá data (hlavně chvíli po startu), má ve statusu ⏳.

## 1.6 · 2026-11-20 · Pizza dne v La Stradě 🍕

- 🍕 V `/restaurace` je pizza dne La Strady zvlášť pod ostatními jídly a u každé ze 4 pizz jsou ingredience.

## 1.5 · 2026-11-20 · Rychlost ⚡

- ⚡ Všechny commandy odpovídají hned, slevy dřív trvaly i několik sekund. Bot si data stahuje průběžně sám: menzy každých 10 minut, restaurace každou půlhodinu, výluky MHD každých 5 minut a slevy s letáky každou hodinu. Tlačítko 🔄 Obnovit stáhne data hned.

## 1.4 · 2026-11-20 · Pivo 🍺

- 🍺 Nový command `/pivo` ukáže pivo v akci v Lidlu, BILLE, Albertu a Globusu. Tlačítky se dá vybrat jen lahve 🍾, plechovky 🥫, nebo basy a multipacky 📦. U multipacků je cena za litr. Piva se jmenují tak, jak se jim říká (**Kozel** 12° ležák). PET lahve, sudy a dárková balení s krýglem se nezobrazují.
- ✨ Přehlednější výpisy slev: sleva v % je na začátku řádku pod sebou, stejná akce se neukazuje dvakrát a obchody, kde nic není, jsou jen vyjmenované nahoře. U akcí a letáků, které teprve začnou, je „📅 od …“.
- 🛒 Obchody se ve slevách jmenují obecně (Lidl, BILLA, Albert supermarket, Globus), protože akce platí pro celý řetězec. Konkrétní pobočka je vidět u `/letaky`, kde se letáky a otevírací doba opravdu liší.

## 1.3 · 2026-11-20 · Nápoje bez cukru

- 🥤 Nový command `/napoje` ukáže energetické nápoje a limonády bez cukru v akci ve stejných obchodech jako `/maso`. ✅ znamená výslovně bez cukru (Zero, bez cukru…), 🤷 akci na „různé druhy“ značky, která verzi bez cukru vyrábí.
- 🏷️ Slevy se otevírají rovnou s filtrem **Jen se slevou**, který ukáže jen akce s uvedenou slevou v %. Tlačítkem se dá vypnout a ukázat všechny akce.
- 📰 `/slevy` se teď jmenuje `/letaky`, protože ukazuje akční letáky.

## 1.2 · 2026-11-20 · Slevy v supermarketech

- 🛒 Nový command `/slevy` ukáže aktuální akční letáky pro Lidl (Palackého, Šumavská, Bayerova), BILLA Srbská, Albert Semilasso a Globus Ivanovice. U každého obchodu je i dnešní otevírací doba.
- 🥩 Nový command `/maso` ukáže slevy na maso v těchhle obchodech, seřazené podle výše slevy. Tlačítky se dá vybrat jen vepřové, hovězí nebo drůbež. U akcí, které teprve začnou, je vidět, odkdy platí.

## 1.1 · 2026-11-20 · Novinky v botovi

- 🆕 Nový command `/novinky` ukáže, co je nového v posledních verzích bota. Tlačítky se dá listovat i ke starším verzím.
- 🏷️ Ve statusu bota je číslo verze (třeba „verze 1.1“), takže je hned vidět, jestli už běží ta nová.

## 1.0 · 2026-11-20 · První verze

### 🍽️ Obědy
- `/ppv`, `/purkyne` a `/menzy` ukážou Economy jídla v menzách VUT. Tlačítkem se dá přepnout i na všechna jídla (bez salátů a příloh) nebo na jiné menzy.
- U každé menzy je dnešní otevírací doba.
- `/restaurace` ukáže polední menu U 3 opic, Padagali, La Strada, U Karla a Portoriko.
- Každé jídlo má emoji podle toho, co to je 🍗🐖🍕🍛

### 🚏 MHD
- `/mhd` ukáže nejbližší odjezdy u PPV: tramvaje z Technologického parku a autobusy z Kolejní. U 72 je vidět, jestli jede dál směr Semilasso, nebo na Technoparku končí.
- `/mhd-purkyne` ukáže odjezdy u kolejí Purkyňova: tramvaje z Červinkovy a autobusy ze Skácelovy (zvlášť na východ a na západ).
- U odjezdů jsou vidět aktuální výluky na těch linkách.

### 💬 Ostatní
- Commandy fungují i v soukromém chatu s botem.
- Když se něco pokazí, bot pošle odkaz, kam chybu nahlásit.
