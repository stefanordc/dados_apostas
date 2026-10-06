from src.repositories.history_repository import COLUMN_ALIASES
from src.utils import normalize_text


def test_portuguese_home_away_aliases():
    home_aliases = {normalize_text(x) for x in COLUMN_ALIASES["mandante"]}
    away_aliases = {normalize_text(x) for x in COLUMN_ALIASES["visitante"]}
    assert "casa" in home_aliases
    assert "fora" in away_aliases
