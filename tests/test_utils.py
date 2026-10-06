from src.utils import normalize_season, normalize_text


def test_normalize_season_year():
    assert normalize_season("2026") == "2026"


def test_normalize_season_range():
    assert normalize_season("2025-2026") == "2025/2026"


def test_normalize_text_accents():
    assert normalize_text("Gols Casa") == "gols_casa"
    assert normalize_text("País") == "pais"
