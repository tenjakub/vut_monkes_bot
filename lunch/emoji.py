"""Přiřazení emoji k jídlu podle klíčových slov v názvu.

Jak se vybírá:
1. **Typ jídla** (pizza, kari, wok, burrito, palačinky…) vyhrává vždy, kdekoli v názvu.
2. Jinak rozhoduje **surovina, která je v názvu nejdřív** – v českých jídelníčcích je hlavní
   složka skoro vždy první ("Kuřecí plátek se slaninou, hranolky" → kuře, ne slanina ani hranolky).
   Při shodě pozice vyhrává delší shoda ("bramborové knedlíky" před "brambor").

Regexy se pouští na text bez diakritiky a malými písmeny, takže stačí psát "kurec", ne "kuřec".
Pro přidání pravidla stačí připsat řádek do TYPES nebo INGREDIENTS.
"""

from __future__ import annotations

import re
import unicodedata

from .models import Category, Dish

FALLBACK = "🍽️"
SOUP = "🥣"

# (emoji, regex) – úroveň 1: typ jídla, vyhrává bez ohledu na pozici
TYPES: list[tuple[str, str]] = [
    ("🍕", r"pizz|calzone"),
    ("🍔", r"burger"),
    ("🌭", r"hot ?dog"),
    ("🌯", r"burrito|tortill|\bwrap|quesadill|fajit|enchilad"),
    ("🌮", r"\btacos?\b|nachos"),
    ("🥙", r"kebab|gyros|doner|falafel|shawarm"),
    ("🍣", r"sushi|\bmaki\b|\bpoke\b|onigiri"),
    ("🍛", r"\bkari\b|curry|masala|korma|madras|tikka|vindaloo|thali|\bdal\b|paneer|biryani|tandoori"),
    ("🍜", r"\bwok|ramen|\bpho\b|pad ?thai|yakisob|chow mein|udon|mie goreng"),
    ("🍝", r"spaget|spaghet|lasagn|tagliatel|\bpenne|carbonar|bolon|fusill|farfall|tortellin|raviol"
           r"|gnocch|testovin|\bpasta\b|makaron|linguin|pappardel"),
    ("🥘", r"paella"),
    ("🥗", r"^salat|\bsalad\b|caesar"),
    ("🧀", r"smazeny syr|smazeny hermelin|grilovany hermelin|nakladany hermelin"),
    ("🥞", r"palacin|livanc|vafl|crepe"),
    ("🍰", r"kolac|\bdort|strudl|\bzavin|tiramisu|cheesecake|muffin|brownie"),
    ("🥮", r"buchty|buchtick"),
    ("🍪", r"cookies|susenk"),
    ("🍩", r"donut|koblih"),
    ("🍮", r"nakyp|pudink|krupicov\w* kas|panna cotta"),
    ("🫐", r"ovocn\w* knedl|kynut\w* knedl|tvarohov\w* knedl|marmelad|povidl"),
    ("🍨", r"zmrzlin"),
]

# úroveň 2: suroviny, vyhrává ta nejdřív zmíněná
INGREDIENTS: list[tuple[str, str]] = [
    # ryby a mořské plody
    ("🐟", r"\bryb|losos|tresk|pstruh|\bkapr|okoun|tunak|tilapi|pangas|candat|\bsumec|makrel|hejk"
           r"|aljask|\bfish"),
    ("🦐", r"kreve|scamp|garnat|chobotn|kalamar|morsk\w* plod|musl"),
    # maso
    ("🦆", r"\bkach"),
    ("🦃", r"\bkrut(a|y|i|ou|e)\b|\bkruti"),
    ("🐇", r"\bkralic|\bkralik"),
    ("🦌", r"\bjelen|\bsrnc|\bdivoc|\bdivak|zverin|\bdanek|\bdanci"),
    ("🐑", r"jehnec|jehne|skopov"),
    ("🍗", r"\bkur(e|ec|at)|chicken|drubez|\bkridl|\bstehn"),
    ("🐄", r"\bhovez|\bbeef|\btelec|svickov|rostenk|roastbeef|biftek"),
    ("🐖", r"\bvepr|\bpork|panenk|krkovic|\bbucek|kotlet"),
    ("🥩", r"steak"),
    ("🥓", r"slanin|bacon|\buzen|\bsunk|\bspek"),
    ("🌭", r"\bparek|\bparky|\bparku|klobas|vurst|jitrnic|jelit|\bprejt|tlacenk"),
    ("🍖", r"\bmaso|\bmasa\b|masov|sekan|karbanat|fasirk|cevapcic|\brizek|schnitzel|spiz"),
    # bezmasé hlavní složky
    ("🍄", r"zampion|\bhrib|\bhoub|hlivu|hliva|\blisky\b|\bliskami\b"),
    ("🧀", r"\bsyr|mozzarel|cheddar|hermelin|\bniva|\bnivou|eidam|gouda|parmez|halloumi|brynz|ricott"),
    ("🍳", r"\bvejc|\bvajec|\bvejce|omelet|\begg"),
    ("🌱", r"\bvegan|\btofu|tempeh|seitan|\bsoj"),
    ("🫛", r"\bhrach|\bhrasek|\bhrask"),
    ("🫘", r"fazol|cizrn|\bcock"),
    ("🥟", r"knedl|bramborov\w* knedl|pelmen|\bpirog|pirohy|gyoz|dumpling"),
    ("🥔", r"brambor|halusk|kroket|\bkase\b|\bkasi\b|\bkasí"),
    ("🍟", r"hranol"),
    ("🍚", r"rizot|risott|\bryz"),
    ("🍞", r"\bchleb|toast|sendvic|bageta|bagel|\bbulk|focacc|langos|\bpecivo"),
    # zelenina
    ("🥦", r"brokolic|kvetak|zelenin"),
    ("🥬", r"spenat|\bzeli\b|\bzelim|kapust|\bkedluben"),
    ("🍆", r"\blilek|baklaz"),
    ("🍅", r"rajc"),
    ("🫑", r"paprik"),
    ("🥕", r"mrkev|mrkv"),
    ("🌽", r"kukuric"),
    ("🎃", r"\bdyn"),
]

_TYPES = [(e, re.compile(p)) for e, p in TYPES]
_INGREDIENTS = [(e, re.compile(p)) for e, p in INGREDIENTS]


def _simplify(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _first_match(text: str, rules: list[tuple[str, re.Pattern[str]]]) -> str | None:
    best: tuple[int, int, int] | None = None
    best_emoji = None
    for priority, (emoji, pattern) in enumerate(rules):
        m = pattern.search(text)
        if m is None:
            continue
        key = (m.start(), -(m.end() - m.start()), priority)
        if best is None or key < best:
            best, best_emoji = key, emoji
    return best_emoji


def for_name(name: str) -> str:
    text = _simplify(name)
    return _first_match(text, _TYPES) or _first_match(text, _INGREDIENTS) or FALLBACK


def for_dish(dish: Dish) -> str:
    if dish.category is Category.SOUP:
        return SOUP
    return for_name(dish.name)
