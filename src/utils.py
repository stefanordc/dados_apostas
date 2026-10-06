from __future__ import annotations

import re
import unicodedata
from decimal import Decimal


def normalize_text(value: str) -> str:
    value = (value or "").strip()
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", normalized.lower()).strip("_")
    return normalized


def normalize_season(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", "", value)
    value = value.replace("-", "/").replace("_", "/").replace("\\", "/")
    if not re.fullmatch(r"\d{4}(/\d{4})?", value):
        raise ValueError("Temporada inválida. Use 2026 ou 2025/2026.")
    if "/" in value:
        first, second = map(int, value.split("/"))
        if second < first or second > first + 2:
            raise ValueError("Temporada inválida. Exemplo esperado: 2025/2026.")
    return value


def currency_label(code: str) -> str:
    return {"EUR": "Euro", "USD": "Dólar", "BRL": "Real"}.get(code, code)


def format_number_br(value: int | float | Decimal | None, decimals: int = 0) -> str:
    if value is None:
        return "0"
    number = float(value)
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")
