"""Países disponíveis nos filtros de análise, conforme jogos realmente gravados.

O banco do catálogo e o histórico podem usar conexões distintas. Por isso
consultamos os países de cada fonte separadamente, sem JOIN entre bancos.
"""

import time
import unicodedata
from functools import lru_cache

from sqlalchemy import text

from ..config import settings
from ..db import history_connection


def _country_key(value: str) -> str:
    """Ignora apenas diferenças de acento, maiúsculas e espaços nas grafias."""
    cleaned = unicodedata.normalize("NFKD", str(value or ""))
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    return " ".join(cleaned.casefold().split())


@lru_cache(maxsize=2)
def _countries_with_games_cached(bucket: int) -> frozenset[str]:
    with history_connection() as conn:
        names = conn.execute(text(f"""
            SELECT DISTINCT pais
            FROM {settings.history_schema}.{settings.history_table}
            WHERE pais IS NOT NULL AND BTRIM(pais) <> ''
        """)).scalars().all()
    return frozenset(key for name in names if (key := _country_key(name)))


def filter_countries_with_games(countries: list[dict]) -> list[dict]:
    """Mantém somente países com pelo menos uma partida em historico_jogos.

    Cache dura até 60 s para não ler a tabela inteira a cada filtro. Quando um
    país ganha seu primeiro jogo, aparece após o período curto de atualização.
    """
    available = _countries_with_games_cached(int(time.time() // 60))
    return [country for country in countries if _country_key(country.get("nome")) in available]
