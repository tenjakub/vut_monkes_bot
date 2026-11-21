"""/restaurace: tlačítka s odkazy na restaurace se musí vejít do řad po pěti."""

from cogs import restaurace
from lunch import service


def test_buttons_fit_rows():
    view = restaurace.build_view()  # discord.py by při přeplněné řadě spadl už tady
    links = [i for i in view.children if getattr(i, "url", None)]
    assert len(links) == len(service.RESTAURANTS)
    assert max(i.row for i in view.children) <= 4
