from datetime import datetime

from lunch.models import Dish, Menu, Place
from lunch.service import TZ
from utils import render

PLACE = Place("x", "Testovací menza", "https://example.invalid")


def names(embed):
    return [(f.name, f.inline) for f in embed.fields]


def test_last_grid_row_is_padded():
    dishes = [Dish(f"Kuřecí jídlo {i}", "100 Kč", label=f"E{i}") for i in range(1, 5)]
    fields = [render.dish_field(d) for d in dishes]
    embed = render.menu_embed(Menu(PLACE, dishes), fields, 4000, "")
    # 4 kartičky -> 2 plné řady po 3 (2 prázdné doplňky)
    assert len(embed.fields) == 6
    assert [f.name for f in embed.fields[4:]] == [render.BLANK, render.BLANK]
    assert all(f.inline for f in embed.fields)


def test_row_closed_before_full_width_field():
    soup = Dish("Polévka česneková", category=render.emoji.Category.SOUP)
    main = Dish("Kuřecí plátek", "100 Kč")
    fields = [render.dish_field(main)] + render.soup_field([soup])
    embed = render.menu_embed(Menu(PLACE, [main, soup]), fields, 4000, "")
    assert [f.inline for f in embed.fields] == [True, True, True, False]


def test_header_has_discord_timestamps():
    ts = datetime(2026, 11, 20, 11, 0, tzinfo=TZ)
    text = render.header("🍽️ Economy menu", [Menu(PLACE, fetched_at=ts)], "ceny pro studenty")
    unix = int(ts.timestamp())
    assert f"<t:{unix}:t>" in text and f"<t:{unix}:R>" in text
    assert text.startswith("### 🍽️ Economy menu – ")
