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

## 1.21 · 2026-11-23 · Nastavení serveru ⚙️

- ⚙️ Nový command `/nastaveni` jen pro adminy serveru: dá se v něm nastavit, od kolika lidí bot zakládá událost z `/na-pivo` (2–5), nebo že ji nezakládá vůbec.

## 1.20 · 2026-11-23 · Moje koleje 🏠

- 🏠 Nový command `/koleje`: nastav si, jestli bydlíš na PPV, nebo na Purkyních. `/mhd` a `/kola` ti pak rovnou ukážou tvoje koleje (přepínat jde dál tlačítky). Kdo nic nenastaví, má všechno jako dřív.

## 1.19 · 2026-11-23 · Ceny piva v hospodách 🍺

- 🍺 Nový command `/cena-piva`: kdokoli může zapsat, jaká piva se v hospodách z `/na-pivo` točí a kolik stojí půllitr. Každé pivo jde zvlášť upravit nebo smazat. Pro hospody s velkým výběrem (Pivní burza) stačí zadat „🍻 víc druhů, kolem 70 Kč“. Jde to i z 🗺️ **Kde co je** u pozvánky.
- 💰 Ceny se ukazují v pozvánce `/na-pivo` u vybraného podniku, v 🗺️ Kde co je a ve výběru „Kam“. Jedno nebo dvě piva jsou vypsaná rovnou, u víc piv je jen jejich počet a obvyklá cena (~ = medián).
- ↩️ Každá změna se pamatuje i s tím, kdo ji udělal, takže když někdo zadá nesmysl, jde to výběrem vrátit na kterýkoli dřívější stav.

## 1.18 · 2026-11-23 · Hlídání akcí 🔔

- 🔔 Nový command `/hlidat`: napíšeš, co chceš hlídat (třeba `Monster`, `Plzeň`, `kuřecí prsa`), a případně cenu, do které to bereš. Jakmile to bude v Lidlu, BILLE, Albertu nebo Globusu v akci, bot ti napíše do soukromé zprávy. Co je v akci už teď, ukáže hned. Hlídá se maso, nápoje a pivo.

## 1.17 · 2026-11-23 · Dobrá cena, nebo past? 🔥

- 🔥 V `/maso`, `/napoje` a `/pivo` je u ceny 🔥, když je to nejlevnější, za kolik jsme produkt v akci viděli, a 🎣, když je sleva jen na oko (jinde nebo jindy bývá v akci levněji). Bot si ceny akcí pamatuje, takže čím déle běží, tím je to přesnější.

## 1.16 · 2026-11-23 · Hodnocení jídel ⭐

- ⭐ Pod `/ppv`, `/purkyne`, `/menzy` a `/restaurace` je tlačítko **Ohodnotit**: vybereš, co sis dal(a), a dáš 👍 dobré, 😐 neurazí nebo 👎 špatné. Vidíš to jen ty, a kdyby ses překlikl(a), jde to hned zrušit.
- Souhrn hodnocení je nevýrazně pod jídlem ve výpisu (třeba „👍 3 · 😐 1“) a platí i příště, až se stejné jídlo zase vaří.

## 1.15 · 2026-11-22 · Statistiky 📊

- 📊 Nový command `/statistiky` ukáže, které commandy bota se používají nejvíc, za posledních 7 nebo 30 dní i od začátku. Počítá se jen kolikrát se který command použil, ne kdo ho použil.

## 1.14 · 2026-11-22 · Událost na pivo 📅

- 📅 Když na pozvánku `/na-pivo` klikne **✅ Jdu** aspoň 3 lidi a je vybraný čas, bot založí na serveru událost s místem a časem. Odkaz na ni je v pozvánce a když se změní čas nebo místo, událost se sama upraví.

## 1.13 · 2026-11-22 · Kola 🚲

- 🚲 Nový command `/kola` ukáže volná kola nextbike na stanicích kolem kolejí PPV, seřazené od nejbližší, i s tím, kolik minut je to pěšky. Kliknutím na stanici se otevře v aplikaci nextbike. Tlačítky se dá přepnout na stanice u Purkyní a u FITu. Když v okolí žádné kolo není, bot napíše, kde je nejbližší.

## 1.12 · 2026-11-22 · Co je otevřeno 🕐

- 🕐 Nový command `/otevreno` ukáže, co má teď otevřeno: menzy, pizzerie, kavárny a bufety VUT a okolní Lidly, BILLA, Albert a Globus. U každého místa je, do kolika má otevřeno, kdy otevře, nebo jak má otevřeno zítra. Otevřená místa jsou nahoře. Bot ví i o svátcích, kdy mají velké obchody ze zákona zavřeno.


## 1.11.1 · 2026-11-22 · Spolehlivější tlačítka

- 🛠️ Když se po kliknutí na tlačítko něco pokazí, bot to napíše (jen tobě) i s odkazem, kam chybu nahlásit. Dřív se prostě nic nestalo.
- 🍽️ Když v `/obed` nebo `/na-pivo` klikne víc lidí skoro naráz, započítají se všichni. Dřív mohlo jedno kliknutí přepsat druhé.
- 📅 Hlasování `/obed` si drží datum, kdy bylo svolané, i když na něj někdo klikne až další den.


## 1.11 · 2026-11-21 · Sesamo 🥐

- 🥐 `/restaurace` ukazuje i denní menu **Sesamo** (italská pekárna a pizzerie na Purkyňově 97c), a to i o víkendu. Saláty a hlavní jídla jsou v mřížce, těstoviny a pizzy pod nimi a u pizz jsou i přísady z jejich velkého menu. Sesamo jde vybrat i v `/obed` a losuje z něj `/co-jist`.

## 1.10 · 2026-11-21 · Počasí na pivo ☀️

- ☀️ V `/na-pivo-termin` má každý den na tlačítku ikonku počasí na večer a u nejlepšího termínu je předpověď na čas, od kdy můžou všichni. Pozvánka `/na-pivo` ukazuje počasí na vybraný čas.
- 🎂 `/pocasi` ukáže, kdo má dnes svátek.

## 1.9.1 · 2026-11-21 · U Karla i o víkendu

- 🍺 `/restaurace` ukazuje polední menu U Karla i o víkendu. Bot ho teď bere přímo z jejich webu, kde je na celý týden včetně soboty a neděle.

## 1.9 · 2026-11-21 · Na pivo 🍺

- 🍺 Nový command `/na-pivo` svolá dnešní pivo. Ve výběrech pod zprávou se nastaví, v kolik a kam se jde (kdokoliv to může změnit), a každý klikne **✅ Jdu**, **📅 Jindy** nebo **❌ Nejdu**. U vybrané hospody je adresa a odkaz na mapu.
- 🗓️ Nový command `/na-pivo-termin` hledá společný den v příštích dvou týdnech. Klikneš na každý den, kdy můžeš, a vybereš, od kolika. Nahoře je vidět nejlepší termín 🏆 a tlačítkem **🍺 Svolat nejlepší den** se z něj udělá pozvánka, která označí všechny, kdo ten den můžou.
- 📍 Kam se jde, se vybírá z hospod u PPV, u Purkyní, u FITu a v centru. Když se ještě neví kam přesně, dá se vybrat jen oblast („V centru“) nebo **🎲 Kamkoliv**. Tlačítko **🗺️ Kde co je** ukáže všechny podniky s adresou a mapou.

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
