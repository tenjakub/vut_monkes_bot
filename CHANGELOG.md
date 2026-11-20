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
