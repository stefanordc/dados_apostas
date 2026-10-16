from pydantic import BaseModel, Field
from typing import Optional, Any

class CountryCreate(BaseModel):
    nome: str = Field(min_length=1)
    continente: str = Field(min_length=1)

class CompetitionCreate(BaseModel):
    nome: str = Field(min_length=1)
    pais_id: int
    principal: bool = False

class ClubCreate(BaseModel):
    nome: str = Field(min_length=1)
    pais_id: int
    campeonato_id: Optional[int] = None
    temporada: Optional[str] = None
    escudo_url: Optional[str] = None

class MarketValueCreate(BaseModel):
    temporada: str = Field(min_length=1)
    pais_id: int
    campeonato_id: int
    clube_id: int
    valor: float = Field(gt=0)
    moeda: str


class MarketValueBulkRequest(BaseModel):
    pais_id: int
    campeonato_id: int
    moeda: str
    raw_text: str = Field(min_length=1)

class OddsPreviewRequest(BaseModel):
    pais_id: int
    campeonato_id: int
    temporada: Optional[str] = None
    raw_text: str = Field(min_length=1)

class OddsImportRequest(OddsPreviewRequest):
    mappings: dict[str, int] = {}

class IdName(BaseModel):
    id: int
    nome: str


class ClubUpdate(BaseModel):
    nome: str = Field(min_length=1)
    pais_id: int
    escudo_url: Optional[str] = None

class ClubMembershipCreate(BaseModel):
    campeonato_id: int
    temporada: str = Field(min_length=1)

class ClubMembershipUpdate(BaseModel):
    old_campeonato_id: int
    old_temporada: str = Field(min_length=1)
    campeonato_id: int
    temporada: str = Field(min_length=1)

class SimilarGamesRequest(BaseModel):
    home_id: int
    away_id: int
    competition_id: int
    season: str = Field(min_length=1)
    home_odd: float = Field(gt=1.0)
    draw_odd: float = Field(gt=1.0)
    away_odd: float = Field(gt=1.0)
    odds_tolerance_pct: float = Field(default=10.0, ge=1.0, le=50.0)
    elo_tolerance_points: float = Field(default=50.0, ge=5.0, le=400.0)
    selected_markets: list[str] = []
    market_odds: dict[str, float] = {}
    cutoff_date: Optional[str] = None


class ImportAdditionalClub(BaseModel):
    nome: str = Field(min_length=1, max_length=160)
    clube_id: Optional[int] = None


class ClubSeasonImportRequest(BaseModel):
    campeonato_id: int
    temporada: str = Field(min_length=1)
    clube_ids: list[int] = []
    novos_clubes: list[ImportAdditionalClub] = Field(default_factory=list, max_length=10)


class ValueScannerRequest(BaseModel):
    pais_id: int
    campeonato_id: int
    temporada_alvo: str = Field(min_length=1)
    temporada_corte: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    ev_minimo: float = Field(default=0.0, ge=-50.0, le=100.0)



class ScannerInsightRequest(BaseModel):
    campeonato_id: int
    temporada_alvo: str = Field(min_length=1)
    sequencia_vitorias: int = Field(default=3, ge=1, le=20)
    proximo_mando: str = Field(default="home", pattern="^(home|away|any)$")
    faixa_mo_min: Optional[float] = Field(default=None, gt=1)
    faixa_mo_max: Optional[float] = Field(default=None, gt=1)
    faixa_over25_min: Optional[float] = Field(default=None, gt=1)
    faixa_over25_max: Optional[float] = Field(default=None, gt=1)


class ScannerCondition(BaseModel):
    field: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    # Em comparações campo x campo não existe valor numérico fixo.
    # O frontend envia compare_field e omite value; por isso ambos
    # precisam ser aceitos explicitamente pelo contrato da API.
    value: Optional[Any] = None
    value2: Optional[Any] = None
    compare_field: Optional[str] = None


class ScannerMethodCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=160)
    mercado: str = Field(min_length=1)
    condicoes: list[ScannerCondition] = Field(default_factory=list)




class ScannerGenerateMethodsRequest(BaseModel):
    campeonato_id: int
    temporada_alvo: str = Field(min_length=1)
    quantidade: int = Field(default=10, ge=1, le=20)


class ScannerBacktestRequest(BaseModel):
    pais_id: int
    campeonato_id: int
    temporada_alvo: str = Field(min_length=1)
    metodo_id: int
    stake: float = Field(default=100.0, gt=0)
