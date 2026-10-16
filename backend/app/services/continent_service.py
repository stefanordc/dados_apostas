"""Continentes do histórico: valores canônicos e fallback para países antigos.

A fonte de verdade, após a migração, é historico_jogos.continente.
Entradas não classificadas continuam como 'Não informado', sem chute.
"""
from __future__ import annotations
import unicodedata

COUNTRIES = {
    'América do Sul': 'Argentina;Bolívia;Brasil;Brazil;Chile;Colômbia;Colombia;Equador;Ecuador;Paraguai;Peru;Uruguai;Venezuela;Guiana;Guyana;Suriname;América do Sul;America do Sul;CONMEBOL',
    'América do Norte': 'Estados Unidos;United States;USA;US;Canadá;Canada;México;Mexico;Costa Rica;Panamá;Panama;Honduras;Guatemala;Nicarágua;Nicaragua;El Salvador;Jamaica;Cuba;Haiti;Haití;República Dominicana;Dominican Republic;Trinidad e Tobago;Trinidad and Tobago;Porto Rico;Puerto Rico;América do Norte;America do Norte;América Central;Caribe;CONCACAF',
    'Europa': 'Alemanha;Germany;Áustria;Austria;Bélgica;Belgium;Bielorrússia;Belarus;Bósnia e Herzegovina;Bosnia and Herzegovina;Bulgária;Bulgaria;Croácia;Croatia;Chipre;Cyprus;Dinamarca;Denmark;Escócia;Scotland;Eslováquia;Slovakia;Eslovênia;Slovenia;Espanha;Spain;Estônia;Estonia;Finlândia;Finland;França;France;Geórgia;Georgia;Grécia;Greece;Holanda;Países Baixos;Netherlands;Hungria;Hungary;Inglaterra;England;Irlanda;Ireland;Irlanda do Norte;Northern Ireland;Islândia;Iceland;Itália;Italy;Kosovo;Letônia;Latvia;Lituânia;Lithuania;Luxemburgo;Luxembourg;Macedônia do Norte;North Macedonia;Malta;Moldávia;Moldova;Montenegro;Noruega;Norway;País de Gales;Wales;Polônia;Poland;Portugal;República Tcheca;Czech Republic;Chéquia;Romênia;Romania;Rússia;Russia;Sérvia;Serbia;Suécia;Sweden;Suíça;Switzerland;Turquia;Turkey;Turkiye;Ucrânia;Ukraine;Europa;UEFA',
    'Ásia': 'Arábia Saudita;Saudi Arabia;Bahrein;Bahrain;Bangladesh;Catar;Qatar;China;Coreia do Sul;South Korea;Coreia do Norte;North Korea;Emirados Árabes Unidos;United Arab Emirates;Filipinas;Philippines;Hong Kong;Índia;India;Indonésia;Indonesia;Irã;Iran;Iraque;Iraq;Israel;Japão;Japan;Jordânia;Jordan;Cazaquistão;Kazakhstan;Kuwait;Kuwait;Líbano;Lebanon;Malásia;Malaysia;Omã;Oman;Paquistão;Pakistan;Palestina;Palestine;Singapura;Singapore;Síria;Syria;Tailândia;Thailand;Taiwan;Uzbequistão;Uzbekistan;Vietnã;Vietnam;Ásia;Asia;AFC',
    'África': 'África do Sul;South Africa;Argélia;Algeria;Angola;Benim;Benin;Botsuana;Botswana;Burkina Faso;Camarões;Cameroon;Cabo Verde;Cape Verde;Costa do Marfim;Ivory Coast;Côte d’Ivoire;Egito;Egypt;Etiópia;Ethiopia;Gabão;Gabon;Gana;Ghana;Guiné;Guinea;Quênia;Kenya;Líbia;Libya;Mali;Marrocos;Morocco;Moçambique;Mozambique;Namíbia;Namibia;Nigéria;Nigeria;Quênia;Senegal;Sudão;Sudan;Tanzânia;Tanzania;Tunísia;Tunisia;Uganda;Zâmbia;Zambia;Zimbábue;Zimbabwe;África;Africa;CAF',
    'Oceania': 'Austrália;Australia;Nova Zelândia;New Zealand;Fiji;Fiji;Ilhas Salomão;Solomon Islands;Papua-Nova Guiné;Papua New Guinea;Taiti;Tahiti;Vanuatu;Nova Caledônia;New Caledonia;Oceania;OFC',
    'Intercontinental': 'Mundo;World;Internacional;International;Global;Intercontinental;FIFA',
}

def key(text: str | None) -> str:
    raw = unicodedata.normalize('NFKD', str(text or ''))
    return ' '.join(''.join(ch for ch in raw if not unicodedata.combining(ch)).casefold().split())

COUNTRY_TO_CONTINENT = {key(name): continent for continent, countries in COUNTRIES.items() for name in countries.split(';')}
CONTINENTS = list(COUNTRIES) + ['Não informado']


def for_country(country: str | None, stored: str | None = None) -> str:
    if stored and str(stored).strip():
        candidate = str(stored).strip()
        return next((c for c in CONTINENTS if key(c) == key(candidate)), candidate)
    return COUNTRY_TO_CONTINENT.get(key(country), 'Não informado')


def allowed_countries(continent: str | None, source: list[dict]) -> list[str]:
    return sorted({str(row['country']) for row in source if not continent or
                   for_country(row.get('country'), row.get('continent')) == continent})
