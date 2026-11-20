import pytest

from lunch import emoji
from lunch.models import Category, Dish


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # hlavní surovina je první, přílohy ani doplňky nerozhodují
        ("Kuřecí plátek 150g s angl.slaninou a sýrem, Rýže jasmínová", "🍗"),
        ("Vepřové nudličky po mexicku, Brambory maštěné máslem", "🐖"),
        ("Pečený okoun na másle, fazolové ragú, opékané grenaille", "🐟"),
        ("Jelení maso na víně a jalovci, Bramborové krokety", "🦌"),
        ("Hrachová kaše, uzené maso, chléb, okurek", "🫛"),  # "okurek" není kuře
        ("Mexické fazole s klobásou, zeleninou", "🫘"),
        ("Bramborové knedlíky s uzeným masem, zelí", "🥟"),
        ("Smažený květák, tatarská omáčka", "🥦"),
        ("Jitrnicový prejt, zelí", "🌭"),
        # typ jídla vyhrává, i když je v názvu až později
        ("Kuřecí rizoto na kari s restovanou zeleninou", "🍛"),
        ("CHICKEN KORMA Kuřecí kostky v jemné smetanové omáčce", "🍛"),
        ("Kuřecí Wok se zeleninou, rýžové nudle", "🍜"),
        ("Hovězí burrito s masovým ragú", "🌯"),
        ("Pizza dle výběru ze 4 druhů", "🍕"),
        ("Kynuté knedlíky s marmeládou a perníkem", "🫐"),
        ("Koláč čokoládový", "🍰"),
        ("CHICKEN SALAD Čerstvý salát s kousky kuřecího masa", "🥗"),
        # salát jako příloha z jídla salát nedělá
        ("Grilovaná kuřecí prsa v BBQ omáčce se salátem", "🍗"),
        ("Něco úplně neznámého", emoji.FALLBACK),
    ],
)
def test_for_name(name, expected):
    assert emoji.for_name(name) == expected


def test_soup_always_bowl():
    assert emoji.for_dish(Dish("Frankfurtská polévka s párkem", category=Category.SOUP)) == emoji.SOUP
